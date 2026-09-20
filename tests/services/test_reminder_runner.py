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

import json
from datetime import datetime, timedelta, timezone

from ian.domain.events import Event
from ian.domain.members import MemberTier, Platform
from ian.services import reminder_runner
from ian.services.member_service import ReminderRecipient


TARGET_DATE = "2026/07/12"


def event(event_id: int, *, tier: int = 0) -> Event:
    return Event.model_validate(
        {
            "id": event_id,
            "title": f"Event {event_id}",
            "startDate": "2026-07-12T19:00:00+08:00",
            "endDate": "2026-07-12T21:00:00+08:00",
            "minimumTier": tier,
            "slug": f"event-{event_id}",
            "_status": "published",
        }
    )


def recipient(
    platform: Platform = Platform.DISCORD,
    *,
    user_id: int = 1,
    account_id: str = "account-1",
    tier: MemberTier = MemberTier.LECTURE_EXPLORATION,
) -> ReminderRecipient:
    return ReminderRecipient(
        user_id=user_id,
        name="Alice",
        email="alice@example.test",
        platform=platform,
        account_id=account_id,
        tier=tier,
    )


def stub_events(monkeypatch, events: list[Event]) -> None:
    async def list_events_on_date(*_args, **_kwargs):
        return events

    monkeypatch.setattr(
        reminder_runner.event_service,
        "list_events_on_date",
        list_events_on_date,
    )


def test_run_once_with_no_events_skips_member_mcp(monkeypatch):
    stub_events(monkeypatch, [])
    monkeypatch.setattr(
        reminder_runner,
        "load_recipients",
        lambda: (_ for _ in ()).throw(AssertionError("should not load")),
    )

    reminder_runner.run_once(target_date=TARGET_DATE)


def test_run_once_reports_event_mcp_failure(monkeypatch):
    logs = []

    async def fail(*_args, **_kwargs):
        raise RuntimeError("MCP unavailable")

    monkeypatch.setattr(reminder_runner.event_service, "list_events_on_date", fail)
    monkeypatch.setattr(reminder_runner.notifications, "send_log", logs.append)

    reminder_runner.run_once(target_date=TARGET_DATE)

    assert logs == ["```\n[REMINDER] FAILED to load event data\n```"]


def test_run_once_dry_run_does_not_send(monkeypatch, capsys):
    stub_events(monkeypatch, [event(1)])
    monkeypatch.setattr(reminder_runner, "load_recipients", lambda: [recipient()])
    monkeypatch.setattr(
        reminder_runner.notifications,
        "send_notification",
        lambda *_: (_ for _ in ()).throw(AssertionError("should not send")),
    )

    reminder_runner.run_once(target_date=TARGET_DATE, dry=True)

    completed = json.loads(capsys.readouterr().err.splitlines()[-1])
    assert completed["status"] == "dry_run"
    assert completed["event_count"] == 1


def test_run_once_filters_and_combines_events_per_recipient(monkeypatch):
    stub_events(monkeypatch, [event(1), event(2, tier=2)])
    recipients = [
        recipient(account_id="tier-1"),
        recipient(
            Platform.LINE,
            user_id=2,
            account_id="tier-2",
            tier=MemberTier.HANDS_ON,
        ),
    ]
    monkeypatch.setattr(reminder_runner, "load_recipients", lambda: recipients)
    messages = {}
    monkeypatch.setattr(
        reminder_runner.notifications,
        "send_notification",
        lambda target, message: messages.setdefault(target.account_id, message) or True,
    )
    monkeypatch.setattr(reminder_runner.notifications, "send_log", lambda *_: None)
    monkeypatch.setattr(reminder_runner.time, "sleep", lambda *_: None)

    reminder_runner.run_once(target_date=TARGET_DATE)

    assert "Event 1" in messages["tier-1"]
    assert "Event 2" not in messages["tier-1"]
    assert "Event 1" in messages["tier-2"]
    assert "Event 2" in messages["tier-2"]
    assert "簽到碼連結" in messages["tier-1"]


def test_run_once_skips_recipient_without_visible_events(monkeypatch):
    stub_events(monkeypatch, [event(1, tier=3)])
    monkeypatch.setattr(reminder_runner, "load_recipients", lambda: [recipient()])
    monkeypatch.setattr(
        reminder_runner.notifications,
        "send_notification",
        lambda *_: (_ for _ in ()).throw(AssertionError("should not send")),
    )
    monkeypatch.setattr(reminder_runner.notifications, "send_log", lambda *_: None)

    reminder_runner.run_once(target_date=TARGET_DATE)


def test_run_once_uses_taipei_tomorrow_when_date_is_omitted(monkeypatch):
    checked_dates = []

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 12, 31, 23, 30, tzinfo=timezone(timedelta(hours=8)))

    async def list_events_on_date(target_date, *_args, **_kwargs):
        checked_dates.append(target_date)
        return []

    monkeypatch.setattr(reminder_runner, "datetime", FixedDateTime)
    monkeypatch.setattr(
        reminder_runner.event_service,
        "list_events_on_date",
        list_events_on_date,
    )

    reminder_runner.run_once()

    assert [value.isoformat() for value in checked_dates] == ["2027-01-01"]
