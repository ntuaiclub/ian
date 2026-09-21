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
import re
from dataclasses import asdict
from datetime import datetime, timezone

import pytest

from ian.application.chat_history import ChatHistoryService
from ian.domain.members import Platform


class WriterStub:
    def __init__(self, outcome=True):
        self.outcome = outcome
        self.entries = []

    def append(self, entry):
        self.entries.append(entry)
        return self.outcome


class RaisingWriter:
    def append(self, _entry):
        raise RuntimeError("private storage detail")


@pytest.mark.parametrize(
    ("platform", "label"),
    [
        pytest.param(Platform.DISCORD, "Discord", id="discord"),
        pytest.param(Platform.FB, "FB", id="facebook"),
        pytest.param(Platform.LINE, "LINE", id="line"),
    ],
)
def test_record_builds_standard_entry_with_taipei_timestamp(platform, label):
    writer = WriterStub()
    service = ChatHistoryService(
        writer,
        clock=lambda: datetime(2026, 9, 21, 4, 5, 6, tzinfo=timezone.utc),
    )

    assert service.record(
        platform=platform,
        sender_id="sender-1",
        user_name="使用者",
        user_message="問題",
        bot_response="回答",
    )

    assert len(writer.entries) == 1
    record = asdict(writer.entries[0])
    assert record == {
        "timestamp": "2026/09/21 12:05:06",
        "platform": label,
        "sender_id": "sender-1",
        "user_name": "使用者",
        "user_message": "問題",
        "bot_response": "回答",
    }
    assert re.fullmatch(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}", record["timestamp"])


def test_record_returns_writer_failure_without_changing_entry_contract():
    writer = WriterStub(outcome=False)
    service = ChatHistoryService(
        writer,
        clock=lambda: datetime(2026, 9, 21, 12, 5, 6),
    )

    assert not service.record(
        platform=Platform.LINE,
        sender_id="sender-1",
        user_name="Alice",
        user_message="hello",
        bot_response="hi",
    )
    assert writer.entries[0].timestamp == "2026/09/21 12:05:06"


def test_record_sanitizes_writer_exception_and_keeps_it_non_fatal(capsys):
    service = ChatHistoryService(
        RaisingWriter(),
        clock=lambda: datetime(2026, 9, 21, 12, 5, 6),
    )

    assert not service.record(
        platform=Platform.FB,
        sender_id="private-sender",
        user_name="Private Name",
        user_message="private question",
        bot_response="private answer",
    )

    raw_log = capsys.readouterr().err
    entry = json.loads(raw_log)
    assert entry["event"] == "chat_history_write_failed"
    assert entry["component"] == "chat_history_service"
    assert entry["platform"] == "FB"
    assert entry["error_type"] == "RuntimeError"
    for private_value in (
        "private-sender",
        "Private Name",
        "private question",
        "private answer",
        "private storage detail",
    ):
        assert private_value not in raw_log
