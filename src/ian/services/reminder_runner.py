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
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote

from ian.config import TZ_TPE
from ian.services import notifications
from ian.services.event_service import create_event_service
from ian.services.member_service import ReminderRecipient, member_service
from ian.utils.logging import elapsed_ms, log_event

REMINDER_HOUR = 19
REMINDER_MINUTE = 0
_FAILURE_NOTIFICATIONS = {
    "load_events": "FAILED to load event data",
    "load_members": "FAILED to load member data",
}
event_service = create_event_service()


def seconds_until_next_run(
    now: datetime | None = None,
    hour: int = REMINDER_HOUR,
    minute: int = REMINDER_MINUTE,
) -> float:
    current = now or datetime.now(TZ_TPE)
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if current >= target:
        target += timedelta(days=1)
    return (target - current).total_seconds()


def load_recipients() -> list[ReminderRecipient]:
    return asyncio.run(member_service.list_reminder_recipients())


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
        target_date = tomorrow.strftime("%Y-%m-%d")

    normalized_target_date = target_date.replace("/", "-")
    try:
        parsed_target_date = date.fromisoformat(normalized_target_date)
    except ValueError as error:
        _report_job_failure(started_at, target_date, "load_events", error)
        return

    log_event(
        "job_started",
        "reminder_runner",
        status="started",
        job="daily_reminder",
        target_date=target_date,
        dry_run=dry,
    )

    try:
        events = asyncio.run(
            event_service.list_events_on_date(parsed_target_date, viewer_tier=3)
        )
    except Exception as e:
        _report_job_failure(started_at, target_date, "load_events", e)
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
        visible_events = [
            event
            for event in events
            if event_service.can_access(event, int(recipient.tier))
        ]
        if not visible_events:
            continue
        personal_message = event_service.format_events(visible_events)
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

    event_titles = ", ".join(event.title for event in events)
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
