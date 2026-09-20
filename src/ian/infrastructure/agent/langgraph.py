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

import asyncio

from ian.application.agent import AgentRequest
from ian.infrastructure.notifications.discord import DiscordHttpClient


def _load_logging():
    from ian.infrastructure.agent import logging as agent_logging

    return agent_logging


def _load_runtime():
    from ian.infrastructure.agent import runtime

    return runtime


def _load_sessions():
    from ian.infrastructure.agent import sessions

    return sessions


class LangGraphAgentAdapter:
    """Application adapter over Ian's queue-based LangGraph runtime."""

    def __init__(self, discord: DiscordHttpClient, log_channel_id: int):
        self._discord = discord
        self._log_channel_id = log_channel_id

    def _configure_logging(self):
        agent_logging = _load_logging()
        agent_logging.configure_discord_logging(
            self._discord,
            self._log_channel_id,
        )
        return agent_logging

    async def generate(self, request: AgentRequest) -> str:
        self._configure_logging()
        runtime = _load_runtime()
        runtime.start_dispatcher(request.user_name, {"timestamp": request.timestamp})
        return await runtime.chat_with_agent(
            request.session_id,
            request.user_name,
            request.question,
            request.user_role,
            request.timestamp,
            request.channel_id,
            platform=request.platform,
            account_id=request.account_id,
            member=request.member,
        )

    async def clear(self, session_id: str) -> None:
        sessions = _load_sessions()
        await sessions.clear_session(session_id)

    async def startup(self) -> None:
        agent_logging = self._configure_logging()
        await asyncio.to_thread(agent_logging.start_log_processor)
        await asyncio.to_thread(agent_logging.send_startup_notification)
