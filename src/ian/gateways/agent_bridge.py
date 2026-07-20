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
from typing import Any, Awaitable, Callable

from ian.domain.members import User
from ian.gateways.messaging_common import get_current_time
from ian.services.agent import chat_with_agent, parse_no_response, start_dispatcher


@dataclass(frozen=True)
class AgentMessageResult:
    text: str
    should_reply: bool
    reaction_emoji: str | None = None


async def run_agent_message_flow(
    *,
    session_id: str,
    user_name: str,
    user_message: str,
    roles: Any,
    channel_id: str,
    platform: str,
    account_id: str,
    member: User | None = None,
    current_time: dict[str, Any] | None = None,
    start_dispatcher_fn: Callable[[str, dict[str, Any]], Any] = start_dispatcher,
    chat_with_agent_fn: Callable[..., Awaitable[str]] = chat_with_agent,
) -> AgentMessageResult:
    """Run the platform-neutral gateway-to-agent message flow."""
    time_data = current_time or get_current_time()
    start_dispatcher_fn(user_name, time_data)

    response = await chat_with_agent_fn(
        session_id,
        user_name,
        user_message,
        roles,
        time_data["timestamp"],
        channel_id,
        platform=platform,
        account_id=account_id,
        member=member,
    )
    is_no_response, reaction_emoji = parse_no_response(response)
    return AgentMessageResult(
        text=response,
        should_reply=not is_no_response,
        reaction_emoji=reaction_emoji,
    )
