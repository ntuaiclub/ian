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
import multiprocessing
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ian.application.chat_history import ChatHistoryEntry, ChatHistoryService
from ian.domain.members import Platform
from ian.infrastructure.chat_history import JsonlChatHistoryWriter


def _entry(**overrides):
    values = {
        "timestamp": "2026/09/21 12:05:06",
        "platform": "LINE",
        "sender_id": "sender-1",
        "user_name": "使用者 🐈",
        "user_message": "第一行\n第二行",
        "bot_response": "這是回答 ✨",
    }
    values.update(overrides)
    return ChatHistoryEntry(**values)


def _append_records(path: str, worker_id: int, count: int) -> None:
    writer = JsonlChatHistoryWriter(Path(path))
    for index in range(count):
        if not writer.append(_entry(sender_id=f"{worker_id}:{index}")):
            raise RuntimeError("append failed")


def test_append_creates_parent_and_preserves_unicode_jsonl(tmp_path):
    path = tmp_path / "nested" / "chat_history.jsonl"
    writer = JsonlChatHistoryWriter(path)

    assert writer.append(_entry())

    raw = path.read_text(encoding="utf-8")
    assert "使用者 🐈" in raw
    assert "這是回答 ✨" in raw
    assert len(raw.splitlines()) == 1
    assert json.loads(raw) == {
        "timestamp": "2026/09/21 12:05:06",
        "platform": "LINE",
        "sender_id": "sender-1",
        "user_name": "使用者 🐈",
        "user_message": "第一行\n第二行",
        "bot_response": "這是回答 ✨",
    }


def test_append_adds_records_without_rewriting_existing_content(tmp_path):
    path = tmp_path / "chat_history.jsonl"
    writer = JsonlChatHistoryWriter(path)

    assert writer.append(_entry(sender_id="first"))
    first_snapshot = path.read_bytes()
    assert writer.append(_entry(sender_id="second"))

    updated = path.read_bytes()
    assert updated.startswith(first_snapshot)
    records = [json.loads(line) for line in updated.decode("utf-8").splitlines()]
    assert [record["sender_id"] for record in records] == ["first", "second"]


def test_append_preserves_malformed_existing_content_and_starts_a_new_line(tmp_path):
    path = tmp_path / "chat_history.jsonl"
    path.write_text("{malformed", encoding="utf-8")
    writer = JsonlChatHistoryWriter(path)

    assert writer.append(_entry(sender_id="new-record"))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "{malformed"
    assert json.loads(lines[1])["sender_id"] == "new-record"


def test_append_failure_is_sanitized_and_non_fatal(tmp_path, capsys):
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("blocking file", encoding="utf-8")
    writer = JsonlChatHistoryWriter(blocked_parent / "chat_history.jsonl")
    entry = _entry(
        sender_id="private-sender",
        user_name="Private Name",
        user_message="private question",
        bot_response="private answer",
    )

    assert not writer.append(entry)

    raw_log = capsys.readouterr().err
    log_entry = json.loads(raw_log)
    assert log_entry["event"] == "chat_history_write_failed"
    assert log_entry["component"] == "chat_history_writer"
    assert log_entry["platform"] == "LINE"
    assert log_entry["status"] == "error"
    assert log_entry["error_type"] in {"FileExistsError", "NotADirectoryError"}
    for private_value in (
        "private-sender",
        "Private Name",
        "private question",
        "private answer",
    ):
        assert private_value not in raw_log


@pytest.mark.parametrize(
    ("platform", "label"),
    [
        pytest.param(Platform.DISCORD, "Discord", id="discord"),
        pytest.param(Platform.FB, "FB", id="facebook"),
        pytest.param(Platform.LINE, "LINE", id="line"),
    ],
)
def test_service_and_writer_persist_each_platform_contract(tmp_path, platform, label):
    path = tmp_path / "chat_history.jsonl"
    service = ChatHistoryService(
        JsonlChatHistoryWriter(path),
        clock=lambda: datetime(2026, 9, 21, 4, 5, 6, tzinfo=timezone.utc),
    )

    assert service.record(
        platform=platform,
        sender_id="sender-1",
        user_name="使用者",
        user_message="問題",
        bot_response="回答",
    )

    assert json.loads(path.read_text(encoding="utf-8"))["platform"] == label


def test_append_is_safe_across_processes(tmp_path):
    path = tmp_path / "chat_history.jsonl"
    process_count = 4
    records_per_process = 25
    context = multiprocessing.get_context("fork")
    processes = [
        context.Process(
            target=_append_records,
            args=(str(path), worker_id, records_per_process),
        )
        for worker_id in range(process_count)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == process_count * records_per_process
    assert {record["sender_id"] for record in records} == {
        f"{worker_id}:{index}"
        for worker_id in range(process_count)
        for index in range(records_per_process)
    }
