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

import fcntl
import json
import threading
from dataclasses import asdict
from pathlib import Path

from ian.application.chat_history import ChatHistoryEntry
from ian.utils.logging import log_event


class JsonlChatHistoryWriter:
    """Append chat-history entries as UTF-8 JSON Lines records."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def append(self, entry: ChatHistoryEntry) -> bool:
        try:
            encoded_entry = (
                json.dumps(
                    asdict(entry),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
                + b"\n"
            )
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a+b") as history_file:
                    fcntl.flock(history_file.fileno(), fcntl.LOCK_EX)
                    history_file.seek(0, 2)
                    if history_file.tell() > 0:
                        history_file.seek(-1, 2)
                        if history_file.read(1) not in {b"\n", b"\r"}:
                            encoded_entry = b"\n" + encoded_entry
                    history_file.write(encoded_entry)
                    history_file.flush()
            return True
        except Exception as error:
            log_event(
                "chat_history_write_failed",
                "chat_history_writer",
                level="error",
                platform=entry.platform,
                status="error",
                error=error,
            )
            return False
