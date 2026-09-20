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

from ian.application.reminders import ReminderLoadError
from ian.bootstrap import get_application
from ian.domain.time import TZ_TPE
from ian.utils.logging import elapsed_ms, log_event

REMINDER_HOUR = 19
REMINDER_MINUTE = 0
_FAILURE_NOTIFICATIONS = {
    "load_events": "FAILED to load event data",
    "load_members": "FAILED to load member data",
}
application = get_application()
reminder_service = application.reminders
operational_notifier = application.operational_notifications


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
    asyncio.run(
        operational_notifier.send_log(
            f"```\n[REMINDER] {_FAILURE_NOTIFICATIONS[stage]}\n```"
        )
    )


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
        result = asyncio.run(reminder_service.run(parsed_target_date, dry=dry))
    except ReminderLoadError as error:
        _report_job_failure(started_at, target_date, error.stage, error)
        return

    if result.status == "no_events":
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

    if result.status == "dry_run":
        log_event(
            "job_completed",
            "reminder_runner",
            status="dry_run",
            duration_ms=elapsed_ms(started_at),
            job="daily_reminder",
            target_date=target_date,
            event_count=result.event_count,
            recipient_count=result.recipient_count,
        )
        return

    delivery = result.delivery
    if delivery is None:
        raise RuntimeError("completed reminder result requires delivery data")
    event_titles = ", ".join(result.event_titles)
    summary = (
        f"```\n"
        f"[REMINDER] {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Events on {target_date}: {event_titles}\n"
        f"Discord: {delivery.discord_ok} sent, {delivery.discord_fail} failed\n"
        f"Facebook: {delivery.fb_ok} sent, {delivery.fb_fail} failed\n"
        f"LINE: {delivery.line_ok} sent, {delivery.line_fail} failed\n"
        f"Total deliveries: {delivery.sent_count}\n"
        f"```"
    )
    log_event(
        "job_completed",
        "reminder_runner",
        status=delivery.status,
        duration_ms=elapsed_ms(started_at),
        job="daily_reminder",
        target_date=target_date,
        event_count=result.event_count,
        recipient_count=result.recipient_count,
        sent_count=delivery.sent_count,
        failed_count=delivery.failed_count,
    )
    asyncio.run(operational_notifier.send_log(summary))


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
            asyncio.run(operational_notifier.send_log("```\n[REMINDER] ERROR\n```"))
