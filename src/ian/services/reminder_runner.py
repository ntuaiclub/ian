#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Copyright (c) 2026 NTU AI Club
#
# This file is part of Ian, an open-source AI agent framework developed
# and maintained by NTU AI Club.
#
# Ian is licensed under the GNU General Public License, either version 3
# of the License, or (at your option) any later version.
#
# Ian is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ian. If not, see <https://www.gnu.org/licenses/>.
#

import asyncio
import io
import time
from datetime import datetime, timedelta
from urllib.parse import quote

import pandas as pd
import requests

from ian.config import COURSE_DATA_URL, TZ_TPE
from ian.domain.reminders import (
    find_events_on_date,
    format_reminder_message,
    seconds_until_next_run,
)
from ian.services import notifications
from ian.services.member_service import ReminderRecipient, member_service
from ian.utils.logging import elapsed_ms, log_event

REMINDER_HOUR = 19
REMINDER_MINUTE = 0
_FAILURE_NOTIFICATIONS = {
    "fetch_course_data": "FAILED to fetch course data",
    "prepare_events": "FAILED to prepare event data",
    "load_members": "FAILED to load member data",
}


def load_recipients() -> list[ReminderRecipient]:
    return asyncio.run(member_service.list_reminder_recipients())


def fetch_course_data() -> pd.DataFrame:
    if not COURSE_DATA_URL:
        raise RuntimeError("COURSE_DATA_URL is not configured")

    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(COURSE_DATA_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return pd.read_csv(io.StringIO(resp.text))


def _report_job_failure(
    started_at: float,
    target_date: str,
    stage: str,
    error: Exception,
) -> None:
    log_event(
        "job_failed",
        "reminder_runner",
        level="error",
        status="error",
        duration_ms=elapsed_ms(started_at),
        job="daily_reminder",
        stage=stage,
        target_date=target_date,
        error=error,
    )
    notifications.send_log(f"```\n[REMINDER] {_FAILURE_NOTIFICATIONS[stage]}\n```")


def run_once(target_date: str | None = None, dry: bool = False):
    started_at = time.monotonic()
    now = datetime.now(TZ_TPE)

    if target_date is None:
        tomorrow = now + timedelta(days=1)
        target_date = tomorrow.strftime("%Y/%m/%d")

    log_event(
        "job_started",
        "reminder_runner",
        status="started",
        job="daily_reminder",
        target_date=target_date,
        dry_run=dry,
    )

    try:
        df = fetch_course_data()
    except Exception as e:
        _report_job_failure(started_at, target_date, "fetch_course_data", e)
        return

    try:
        events = find_events_on_date(df, target_date)
        message = format_reminder_message(events) if events else ""
    except Exception as e:
        _report_job_failure(started_at, target_date, "prepare_events", e)
        return

    if not events:
        log_event(
            "job_completed",
            "reminder_runner",
            status="success",
            duration_ms=elapsed_ms(started_at),
            job="daily_reminder",
            target_date=target_date,
            event_count=0,
            recipient_count=0,
        )
        return

    try:
        recipients = load_recipients()
    except Exception as e:
        _report_job_failure(started_at, target_date, "load_members", e)
        return

    if dry:
        log_event(
            "job_completed",
            "reminder_runner",
            status="dry_run",
            duration_ms=elapsed_ms(started_at),
            job="daily_reminder",
            target_date=target_date,
            event_count=len(events),
            recipient_count=len(recipients),
        )
        return

    delivery = notifications.empty_delivery_result(recipients)
    for recipient in recipients:
        personal_message = message
        if recipient.name and recipient.email:
            checkin_url = (
                "https://watsonshih.github.io/QuickRecord/user.html?"
                f"name={quote(recipient.name)}&id={quote(recipient.email)}"
            )
            personal_message += f"\n\n簽到碼連結：{checkin_url}"

        try:
            success = notifications.send_notification(recipient, personal_message)
        except Exception as e:
            success = False
            log_event(
                "external_send_failure",
                "reminder_runner",
                level="error",
                platform=recipient.platform.value,
                status="error",
                recipient_id=recipient.account_id,
                operation="send_reminder",
                error=e,
            )
        outcome = "ok" if success else "fail"
        delivery[f"{recipient.platform.value}_{outcome}"] += 1
        time.sleep(0.5)

    event_titles = ", ".join(ev["title"] for ev in events)
    summary = (
        f"```\n"
        f"[REMINDER] {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Events on {target_date}: {event_titles}\n"
        f"Discord: {delivery['discord_ok']} sent, {delivery['discord_fail']} failed\n"
        f"Facebook: {delivery['fb_ok']} sent, {delivery['fb_fail']} failed\n"
        f"LINE: {delivery['line_ok']} sent, {delivery['line_fail']} failed\n"
        f"Total deliveries: {sum(delivery[key] for key in ('discord_ok', 'fb_ok', 'line_ok'))}\n"
        f"```"
    )
    log_event(
        "job_completed",
        "reminder_runner",
        status=(
            "success"
            if sum(delivery[key] for key in ("discord_fail", "fb_fail", "line_fail"))
            == 0
            else "partial_failure"
        ),
        duration_ms=elapsed_ms(started_at),
        job="daily_reminder",
        target_date=target_date,
        event_count=len(events),
        recipient_count=len(recipients),
        sent_count=sum(delivery[key] for key in ("discord_ok", "fb_ok", "line_ok")),
        failed_count=sum(
            delivery[key] for key in ("discord_fail", "fb_fail", "line_fail")
        ),
    )
    notifications.send_log(summary)


def daemon_loop():
    log_event(
        "service_started",
        "reminder_runner",
        status="running",
        service="reminder_daemon",
    )
    while True:
        wait = seconds_until_next_run(hour=REMINDER_HOUR, minute=REMINDER_MINUTE)
        next_run = datetime.now(TZ_TPE) + timedelta(seconds=wait)
        log_event(
            "job_scheduled",
            "reminder_runner",
            status="scheduled",
            job="daily_reminder",
            wait_seconds=wait,
            next_run=next_run.isoformat(),
        )
        time.sleep(wait)
        try:
            run_once()
        except Exception as e:
            log_event(
                "job_failed",
                "reminder_runner",
                level="error",
                status="error",
                job="daily_reminder",
                stage="daemon_loop",
                error=e,
            )
            notifications.send_log("```\n[REMINDER] ERROR\n```")
