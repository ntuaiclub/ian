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

from dataclasses import dataclass
from typing import Protocol

from ian.domain.members import User
from ian.domain.urls import parse_no_response


@dataclass(frozen=True)
class AgentRequest:
    session_id: str
    user_name: str
    question: str
    user_role: str | list[str]
    timestamp: float
    channel_id: str
    platform: str
    account_id: str
    member: User | None = None


@dataclass(frozen=True)
class AgentResult:
    text: str
    should_reply: bool
    reaction_emoji: str | None = None
    reason: str | None = None


class AgentPort(Protocol):
    async def generate(self, request: AgentRequest) -> str: ...

    async def clear(self, session_id: str) -> None: ...

    async def startup(self) -> None: ...


class AgentService:
    def __init__(self, adapter: AgentPort):
        self.adapter = adapter

    async def handle(self, request: AgentRequest) -> AgentResult:
        response = await self.adapter.generate(request)
        is_no_response, reaction_emoji = parse_no_response(response)
        reason = "usage_limit" if "已達今日使用上限" in response else None
        return AgentResult(
            text=response,
            should_reply=not is_no_response,
            reaction_emoji=reaction_emoji,
            reason=reason,
        )

    async def clear(self, session_id: str) -> None:
        await self.adapter.clear(session_id)

    async def startup(self) -> None:
        await self.adapter.startup()
