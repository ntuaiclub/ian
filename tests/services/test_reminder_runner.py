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

from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

from ian.services import reminder_runner


TARGET_DATE = "2026/07/12"
EVENTS = [
    {
        "title": "Agent Evaluation",
        "time": "19:00",
    }
]
MESSAGE = "Hi! 明天 NTUAI 有 Agent Evaluation"


def _stub_event_flow(monkeypatch, bound):
    monkeypatch.setattr(reminder_runner, "fetch_course_data", pd.DataFrame)
    monkeypatch.setattr(reminder_runner, "find_events_on_date", lambda *_: EVENTS)
    monkeypatch.setattr(reminder_runner, "format_reminder_message", lambda *_: MESSAGE)
    monkeypatch.setattr(reminder_runner, "load_members", list)
    monkeypatch.setattr(reminder_runner, "get_valid_bound_members", lambda *_: bound)


def test_run_once_logs_fetch_failure_without_loading_members(monkeypatch):
    logs = []

    def fail_fetch():
        raise RuntimeError("sheet unavailable")

    monkeypatch.setattr(reminder_runner, "fetch_course_data", fail_fetch)
    monkeypatch.setattr(
        reminder_runner,
        "load_members",
        lambda: (_ for _ in ()).throw(AssertionError("members should not be loaded")),
    )
    monkeypatch.setattr(reminder_runner, "send_discord_dm", lambda *_: False)
    monkeypatch.setattr(reminder_runner, "send_log", logs.append)
    monkeypatch.setattr(reminder_runner.time, "sleep", lambda *_: None)

    reminder_runner.run_once(target_date=TARGET_DATE)

    assert logs == [
        "```\n[REMINDER] FAILED to fetch course data: sheet unavailable\n```"
    ]


def test_run_once_with_no_events_does_not_load_members_or_send_messages(monkeypatch):
    monkeypatch.setattr(reminder_runner, "fetch_course_data", pd.DataFrame)
    monkeypatch.setattr(
        reminder_runner,
        "load_members",
        lambda: (_ for _ in ()).throw(AssertionError("members should not be loaded")),
    )
    monkeypatch.setattr(
        reminder_runner,
        "send_discord_dm",
        lambda *_: (_ for _ in ()).throw(AssertionError("DM should not be sent")),
    )
    monkeypatch.setattr(
        reminder_runner,
        "send_log",
        lambda *_: (_ for _ in ()).throw(AssertionError("log should not be sent")),
    )
    monkeypatch.setattr(reminder_runner.time, "sleep", lambda *_: None)

    reminder_runner.run_once(target_date=TARGET_DATE)


def test_run_once_dry_run_lists_recipients_without_sending_messages(
    monkeypatch, capsys
):
    members = [{"name": "Alice"}, {"name": "Bob"}]
    bound = [
        {"name": "Alice", "email": "alice@example.test", "discord_id": "discord-1"},
        {"name": "Bob", "email": "bob@example.test", "discord_id": "discord-2"},
    ]

    monkeypatch.setattr(reminder_runner, "fetch_course_data", pd.DataFrame)
    monkeypatch.setattr(reminder_runner, "find_events_on_date", lambda *_: EVENTS)
    monkeypatch.setattr(reminder_runner, "format_reminder_message", lambda *_: MESSAGE)
    monkeypatch.setattr(reminder_runner, "load_members", lambda: members)
    monkeypatch.setattr(reminder_runner, "get_valid_bound_members", lambda value: bound)
    monkeypatch.setattr(
        reminder_runner,
        "send_discord_dm",
        lambda *_: (_ for _ in ()).throw(AssertionError("DM should not be sent")),
    )
    monkeypatch.setattr(
        reminder_runner,
        "send_log",
        lambda *_: (_ for _ in ()).throw(AssertionError("log should not be sent")),
    )
    monkeypatch.setattr(reminder_runner.time, "sleep", lambda *_: None)

    reminder_runner.run_once(target_date=TARGET_DATE, dry=True)

    captured = capsys.readouterr()
    assert "Would notify 2 member(s)" in captured.err
    assert "Alice (Discord)" in captured.err
    assert "Bob (Discord)" in captured.err


def test_run_once_sends_personalized_messages_and_reports_counts(monkeypatch):
    bound = [
        {
            "name": "王 小明",
            "email": "member+test@example.test",
            "discord_id": "discord-success",
        },
        {
            "name": "Failed Member",
            "email": "failed@example.test",
            "discord_id": "discord-failure",
        },
    ]
    dm_calls = []
    log_calls = []
    sleep_calls = []

    def send_dm(discord_id, message):
        dm_calls.append((discord_id, message))
        return discord_id == "discord-success"

    _stub_event_flow(monkeypatch, bound)
    monkeypatch.setattr(reminder_runner, "send_discord_dm", send_dm)
    monkeypatch.setattr(reminder_runner, "send_log", log_calls.append)
    monkeypatch.setattr(reminder_runner.time, "sleep", sleep_calls.append)

    reminder_runner.run_once(target_date=TARGET_DATE)

    assert dm_calls == [
        (
            "discord-success",
            f"{MESSAGE}\n\n簽到碼連結：https://watsonshih.github.io/QuickRecord/"
            "user.html?name=%E7%8E%8B%20%E5%B0%8F%E6%98%8E&id=member%2Btest%40example.test",
        ),
        (
            "discord-failure",
            f"{MESSAGE}\n\n簽到碼連結：https://watsonshih.github.io/QuickRecord/"
            "user.html?name=Failed%20Member&id=failed%40example.test",
        ),
    ]
    assert sleep_calls == [0.5, 0.5]
    assert len(log_calls) == 1
    assert f"Events on {TARGET_DATE}: Agent Evaluation" in log_calls[0]
    assert "Discord: 1 sent, 1 failed" in log_calls[0]
    assert "Total members notified: 1" in log_calls[0]


def test_run_once_logs_member_load_failure_without_sending_messages(monkeypatch):
    logs = []

    monkeypatch.setattr(reminder_runner, "fetch_course_data", pd.DataFrame)
    monkeypatch.setattr(reminder_runner, "find_events_on_date", lambda *_: EVENTS)
    monkeypatch.setattr(reminder_runner, "format_reminder_message", lambda *_: MESSAGE)
    monkeypatch.setattr(
        reminder_runner,
        "load_members",
        lambda: (_ for _ in ()).throw(ValueError("invalid member JSON")),
    )
    monkeypatch.setattr(
        reminder_runner,
        "send_discord_dm",
        lambda *_: (_ for _ in ()).throw(AssertionError("DM should not be sent")),
    )
    monkeypatch.setattr(reminder_runner, "send_log", logs.append)

    reminder_runner.run_once(target_date=TARGET_DATE)

    assert logs == [
        "```\n[REMINDER] FAILED to load member data: invalid member JSON\n```"
    ]


def test_run_once_continues_after_one_dm_raises(monkeypatch):
    bound = [
        {"name": "Alice", "email": "alice@example.test", "discord_id": "bad"},
        {"name": "Bob", "email": "bob@example.test", "discord_id": "good"},
    ]
    attempted = []
    logs = []

    def send_dm(discord_id, _message):
        attempted.append(discord_id)
        if discord_id == "bad":
            raise TimeoutError("Discord timeout")
        return True

    _stub_event_flow(monkeypatch, bound)
    monkeypatch.setattr(reminder_runner, "send_discord_dm", send_dm)
    monkeypatch.setattr(reminder_runner, "send_log", logs.append)
    monkeypatch.setattr(reminder_runner.time, "sleep", lambda *_: None)

    reminder_runner.run_once(target_date=TARGET_DATE)

    assert attempted == ["bad", "good"]
    assert "Discord: 1 sent, 1 failed" in logs[0]


def test_run_once_with_no_recipients_reports_zero_counts(monkeypatch):
    logs = []

    _stub_event_flow(monkeypatch, [])
    monkeypatch.setattr(
        reminder_runner,
        "send_discord_dm",
        lambda *_: (_ for _ in ()).throw(AssertionError("DM should not be sent")),
    )
    monkeypatch.setattr(reminder_runner, "send_log", logs.append)

    reminder_runner.run_once(target_date=TARGET_DATE)

    assert "Discord: 0 sent, 0 failed" in logs[0]
    assert "Total members notified: 0" in logs[0]


@pytest.mark.parametrize(
    ("name", "email"),
    [
        pytest.param("Alice", "", id="missing-email"),
        pytest.param("", "alice@example.test", id="missing-name"),
        pytest.param("", "", id="missing-name-and-email"),
    ],
)
def test_run_once_omits_checkin_link_without_complete_identity(
    monkeypatch, name, email
):
    bound = [{"name": name, "email": email, "discord_id": "discord-1"}]
    messages = []

    _stub_event_flow(monkeypatch, bound)
    monkeypatch.setattr(
        reminder_runner,
        "send_discord_dm",
        lambda _discord_id, message: messages.append(message) or True,
    )
    monkeypatch.setattr(reminder_runner, "send_log", lambda *_: None)
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
    monkeypatch.setattr(reminder_runner, "send_log", lambda *_: None)

    reminder_runner.run_once()

    assert checked_dates == ["2027/01/01"]
