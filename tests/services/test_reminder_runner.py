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
from datetime import date, datetime, timedelta, timezone

import pytest

from ian.application.notifications import DeliveryReport
from ian.application.reminders import ReminderLoadError, ReminderRunResult
from ian.services import reminder_runner


TARGET_DATE = "2026/07/12"


def stub_result(monkeypatch, result):
    async def run(target_date, *, dry=False):
        assert target_date == date(2026, 7, 12)
        return result

    monkeypatch.setattr(reminder_runner.reminder_service, "run", run)


def test_run_once_logs_no_events(monkeypatch, capsys):
    stub_result(monkeypatch, ReminderRunResult("no_events", (), 0))

    reminder_runner.run_once(target_date=TARGET_DATE)

    completed = json.loads(capsys.readouterr().err.splitlines()[-1])
    assert completed["status"] == "success"
    assert completed["event_count"] == 0


@pytest.mark.parametrize("stage", ["load_events", "load_members"])
def test_run_once_reports_dependency_failure(monkeypatch, stage):
    logs = []

    async def fail(*_args, **_kwargs):
        raise ReminderLoadError(stage, RuntimeError("unavailable"))

    monkeypatch.setattr(reminder_runner.reminder_service, "run", fail)
    monkeypatch.setattr(reminder_runner.notifications, "send_log", logs.append)

    reminder_runner.run_once(target_date=TARGET_DATE)

    expected = reminder_runner._FAILURE_NOTIFICATIONS[stage]
    assert logs == [f"```\n[REMINDER] {expected}\n```"]


def test_run_once_maps_dry_run_result(monkeypatch, capsys):
    stub_result(
        monkeypatch,
        ReminderRunResult("dry_run", ("Event 1",), recipient_count=2),
    )

    reminder_runner.run_once(target_date=TARGET_DATE, dry=True)

    completed = json.loads(capsys.readouterr().err.splitlines()[-1])
    assert completed["status"] == "dry_run"
    assert completed["event_count"] == 1
    assert completed["recipient_count"] == 2


def test_run_once_logs_completed_delivery(monkeypatch):
    delivery = DeliveryReport(
        total_members=2,
        total_recipients=2,
        discord_ok=1,
        line_fail=1,
    )
    stub_result(
        monkeypatch,
        ReminderRunResult("completed", ("Event 1", "Event 2"), 2, delivery),
    )
    logs = []
    monkeypatch.setattr(reminder_runner.notifications, "send_log", logs.append)

    reminder_runner.run_once(target_date=TARGET_DATE)

    assert "Events on 2026/07/12: Event 1, Event 2" in logs[0]
    assert "Discord: 1 sent, 0 failed" in logs[0]
    assert "LINE: 0 sent, 1 failed" in logs[0]


def test_run_once_uses_taipei_tomorrow_when_date_is_omitted(monkeypatch):
    checked_dates = []

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 12, 31, 23, 30, tzinfo=timezone(timedelta(hours=8)))

    async def run(target_date, *, dry=False):
        checked_dates.append(target_date)
        return ReminderRunResult("no_events", (), 0)

    monkeypatch.setattr(reminder_runner, "datetime", FixedDateTime)
    monkeypatch.setattr(reminder_runner.reminder_service, "run", run)

    reminder_runner.run_once()

    assert [value.isoformat() for value in checked_dates] == ["2027-01-01"]


@pytest.mark.parametrize(
    ("hour", "minute", "second", "expected"),
    [
        pytest.param(18, 59, 30, 30, id="before-target"),
        pytest.param(19, 0, 0, 24 * 60 * 60, id="exact-target"),
        pytest.param(20, 0, 0, 23 * 60 * 60, id="after-target"),
    ],
)
def test_seconds_until_next_run_handles_target_boundaries(
    hour, minute, second, expected
):
    now = datetime(
        2026,
        3,
        7,
        hour,
        minute,
        second,
        tzinfo=timezone(timedelta(hours=8)),
    )

    assert reminder_runner.seconds_until_next_run(now, hour=19, minute=0) == expected
