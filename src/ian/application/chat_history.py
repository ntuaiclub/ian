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

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ian.domain.members import Platform
from ian.domain.time import TZ_TPE
from ian.utils.logging import log_event


_PLATFORM_LABELS = {
    Platform.DISCORD: "Discord",
    Platform.FB: "FB",
    Platform.LINE: "LINE",
}


@dataclass(frozen=True)
class ChatHistoryEntry:
    timestamp: str
    platform: str
    sender_id: str
    user_name: str
    user_message: str
    bot_response: str


class ChatHistoryWriter(Protocol):
    """Persist chat-history entries without leaking storage details."""

    def append(self, entry: ChatHistoryEntry) -> bool: ...


class ChatHistoryService:
    """Build normalized chat-history entries and delegate persistence."""

    def __init__(
        self,
        writer: ChatHistoryWriter,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.writer = writer
        self._clock = clock or (lambda: datetime.now(TZ_TPE))

    def record(
        self,
        *,
        platform: Platform,
        sender_id: str,
        user_name: str,
        user_message: str,
        bot_response: str,
    ) -> bool:
        current = self._clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=TZ_TPE)
        timestamp = current.astimezone(TZ_TPE).strftime("%Y/%m/%d %H:%M:%S")
        entry = ChatHistoryEntry(
            timestamp=timestamp,
            platform=_PLATFORM_LABELS[platform],
            sender_id=sender_id,
            user_name=user_name,
            user_message=user_message,
            bot_response=bot_response,
        )
        try:
            return self.writer.append(entry)
        except Exception as error:
            try:
                log_event(
                    "chat_history_write_failed",
                    "chat_history_service",
                    level="error",
                    platform=entry.platform,
                    status="error",
                    error=error,
                )
            except Exception:
                pass
            return False
