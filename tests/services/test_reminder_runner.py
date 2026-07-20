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

import pandas as pd
import pytest

from ian.domain.members import MemberTier, Platform
from ian.services import reminder_runner
from ian.services.member_service import ReminderRecipient


TARGET_DATE = "2026/07/12"
EVENTS = [{"title": "Agent Evaluation", "time": "19:00"}]
MESSAGE = "Hi! 明天 NTUAI 有 Agent Evaluation"


def recipient(
    platform: Platform = Platform.DISCORD,
    *,
    user_id: int = 1,
    account_id: str = "account-1",
    name: str = "Alice",
    email: str = "alice@example.test",
) -> ReminderRecipient:
    return ReminderRecipient(
        user_id=user_id,
        name=name,
        email=email,
        platform=platform,
        account_id=account_id,
        tier=MemberTier.LECTURE_EXPLORATION,
    )


def stub_event_flow(monkeypatch, recipients):
    monkeypatch.setattr(reminder_runner, "fetch_course_data", pd.DataFrame)
    monkeypatch.setattr(reminder_runner, "find_events_on_date", lambda *_: EVENTS)
    monkeypatch.setattr(reminder_runner, "format_reminder_message", lambda *_: MESSAGE)
    monkeypatch.setattr(reminder_runner, "load_recipients", lambda: recipients)


def test_run_once_logs_fetch_failure_without_loading_recipients(monkeypatch):
    logs = []

    def fail_fetch():
        raise RuntimeError("sheet unavailable")

    monkeypatch.setattr(reminder_runner, "fetch_course_data", fail_fetch)
    monkeypatch.setattr(
        reminder_runner,
        "load_recipients",
        lambda: (_ for _ in ()).throw(AssertionError("should not load")),
    )
    monkeypatch.setattr(reminder_runner.notifications, "send_log", logs.append)

    reminder_runner.run_once(target_date=TARGET_DATE)

    assert logs == ["```\n[REMINDER] FAILED to fetch course data\n```"]


def test_run_once_with_no_events_skips_member_mcp(monkeypatch):
    monkeypatch.setattr(reminder_runner, "fetch_course_data", pd.DataFrame)
    monkeypatch.setattr(reminder_runner, "find_events_on_date", lambda *_: [])
    monkeypatch.setattr(
        reminder_runner,
        "load_recipients",
        lambda: (_ for _ in ()).throw(AssertionError("should not load")),
    )

    reminder_runner.run_once(target_date=TARGET_DATE)


def test_run_once_dry_run_reports_multiplatform_recipient_count(monkeypatch, capsys):
    recipients = [recipient(), recipient(Platform.LINE, account_id="line-1")]
    stub_event_flow(monkeypatch, recipients)
    monkeypatch.setattr(
        reminder_runner.notifications,
        "send_notification",
        lambda *_: (_ for _ in ()).throw(AssertionError("should not send")),
    )

    reminder_runner.run_once(target_date=TARGET_DATE, dry=True)

    completed = json.loads(capsys.readouterr().err.splitlines()[-1])
    assert completed["status"] == "dry_run"
    assert completed["recipient_count"] == 2


def test_run_once_personalizes_and_sends_all_platforms(monkeypatch):
    recipients = [
        recipient(Platform.DISCORD, account_id="discord-1"),
        recipient(Platform.FB, account_id="fb-1"),
        recipient(Platform.LINE, account_id="line-1"),
    ]
    sent = []
    logs = []
    stub_event_flow(monkeypatch, recipients)
    monkeypatch.setattr(
        reminder_runner.notifications,
        "send_notification",
        lambda target, message: sent.append((target.platform, message)) or True,
    )
    monkeypatch.setattr(reminder_runner.notifications, "send_log", logs.append)
    monkeypatch.setattr(reminder_runner.time, "sleep", lambda *_: None)

    reminder_runner.run_once(target_date=TARGET_DATE)

    assert [platform for platform, _message in sent] == [
        Platform.DISCORD,
        Platform.FB,
        Platform.LINE,
    ]
    assert all("name=Alice&id=alice%40example.test" in message for _, message in sent)
    assert "Discord: 1 sent, 0 failed" in logs[0]
    assert "Facebook: 1 sent, 0 failed" in logs[0]
    assert "LINE: 1 sent, 0 failed" in logs[0]
    assert "Total deliveries: 3" in logs[0]


def test_run_once_reports_member_mcp_failure(monkeypatch):
    logs = []
    stub_event_flow(monkeypatch, [])
    monkeypatch.setattr(
        reminder_runner,
        "load_recipients",
        lambda: (_ for _ in ()).throw(RuntimeError("MCP unavailable")),
    )
    monkeypatch.setattr(reminder_runner.notifications, "send_log", logs.append)

    reminder_runner.run_once(target_date=TARGET_DATE)

    assert logs == ["```\n[REMINDER] FAILED to load member data\n```"]


def test_run_once_continues_after_delivery_exception(monkeypatch, capsys):
    recipients = [
        recipient(account_id="bad"),
        recipient(Platform.LINE, user_id=2, account_id="good"),
    ]
    attempted = []
    logs = []
    stub_event_flow(monkeypatch, recipients)

    def send(target, _message):
        attempted.append(target.account_id)
        if target.account_id == "bad":
            raise TimeoutError("private timeout")
        return True

    monkeypatch.setattr(reminder_runner.notifications, "send_notification", send)
    monkeypatch.setattr(reminder_runner.notifications, "send_log", logs.append)
    monkeypatch.setattr(reminder_runner.time, "sleep", lambda *_: None)

    reminder_runner.run_once(target_date=TARGET_DATE)

    assert attempted == ["bad", "good"]
    assert "Discord: 0 sent, 1 failed" in logs[0]
    assert "LINE: 1 sent, 0 failed" in logs[0]
    assert "private timeout" not in capsys.readouterr().err


@pytest.mark.parametrize(
    ("name", "email"),
    [("Alice", ""), ("", "alice@example.test"), ("", "")],
)
def test_run_once_omits_checkin_link_without_complete_identity(
    monkeypatch, name, email
):
    messages = []
    stub_event_flow(monkeypatch, [recipient(name=name, email=email)])
    monkeypatch.setattr(
        reminder_runner.notifications,
        "send_notification",
        lambda _target, message: messages.append(message) or True,
    )
    monkeypatch.setattr(reminder_runner.notifications, "send_log", lambda *_: None)
    monkeypatch.setattr(reminder_runner.time, "sleep", lambda *_: None)

    reminder_runner.run_once(target_date=TARGET_DATE)

    assert messages == [MESSAGE]


def test_run_once_uses_taipei_tomorrow_when_target_date_is_omitted(monkeypatch):
    checked_dates = []

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 12, 31, 23, 30, tzinfo=timezone(timedelta(hours=8)))

    monkeypatch.setattr(reminder_runner, "datetime", FixedDateTime)
    monkeypatch.setattr(reminder_runner, "fetch_course_data", pd.DataFrame)
    monkeypatch.setattr(
        reminder_runner,
        "find_events_on_date",
        lambda _df, target_date: checked_dates.append(target_date) or [],
    )

    reminder_runner.run_once()

    assert checked_dates == ["2027/01/01"]
