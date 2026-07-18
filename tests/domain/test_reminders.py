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

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from ian.domain.reminders import (
    clean_value,
    find_events_on_date,
    format_reminder_message,
    seconds_until_next_run,
)


def _event(**overrides):
    event = {
        "date": "2026/03/07",
        "weekday": "六",
        "time": "19:00",
        "venue": "新生",
        "title": "Demo",
        "speaker": "講者",
        "outline": "大綱",
        "target": "社員",
        "livestream": "Y",
        "recording": "N",
        "online_link": "https://meet.example",
        "slides": "",
    }
    event.update(overrides)
    return event


def test_find_events_on_date_matches_only_target_date_and_cleans_empty_values():
    df = pd.DataFrame(
        [
            {
                "時間": "2026/03/07",
                "星期": "六",
                "活動時間": "-",
                "場地": "無",
                "社課主題 / 活動名稱": "Demo",
            },
            {"時間": "2026/03/08", "社課主題 / 活動名稱": "Other"},
        ]
    )

    events = find_events_on_date(df, "2026/03/07")
    assert len(events) == 1
    assert events[0]["title"] == "Demo"
    assert events[0]["date"] == "2026/03/07"
    assert events[0]["time"] == ""
    assert events[0]["venue"] == ""
    assert clean_value(float("nan")) == ""


def test_format_reminder_message_includes_single_event_details():
    message = format_reminder_message([_event()])

    assert "Hi! 明天 NTUAI 有以下活動：" in message
    assert "=== Demo ===" in message
    assert "日期: 2026/03/07 六" in message
    assert "時間: 19:00" in message
    assert "地點: 新生" in message
    assert "講者: 講者" in message
    assert "對象: 社員" in message
    assert "線上直播" in message
    assert "提供錄影" not in message
    assert "課程大綱:\n大綱" in message
    assert "https://meet.example" in message


def test_format_reminder_message_numbers_multiple_events_and_combines_flags():
    message = format_reminder_message(
        [
            _event(title="社課 A", livestream="N", recording="Y"),
            _event(title="社課 B", time="20:00", livestream="Y", recording="Y"),
        ]
    )

    assert "=== [1] 社課 A ===" in message
    assert "=== [2] 社課 B ===" in message
    assert "時間: 20:00" in message
    assert "備註: 提供錄影" in message
    assert "備註: 線上直播 / 提供錄影" in message


def test_format_reminder_message_omits_empty_optional_event_fields():
    message = format_reminder_message(
        [
            _event(
                time="",
                venue="",
                speaker="",
                outline="",
                target="",
                livestream="N",
                recording="N",
                online_link="",
                slides="",
            )
        ]
    )

    assert "=== Demo ===" in message
    assert "日期: 2026/03/07 六" in message
    assert "時間:" not in message
    assert "地點:" not in message
    assert "講者:" not in message
    assert "對象:" not in message
    assert "備註:" not in message
    assert "課程大綱:" not in message
    assert "線上連結:" not in message
    assert "講義:" not in message


def test_format_reminder_message_includes_slides_when_present():
    message = format_reminder_message([_event(slides="https://slides.example/course")])

    assert "講義: https://slides.example/course" in message


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

    assert seconds_until_next_run(now, hour=19, minute=0) == expected
