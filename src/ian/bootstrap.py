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

from ian.application.agent import AgentPort, AgentService
from ian.application.chat_history import ChatHistoryService, ChatHistoryWriter
from ian.application.checkins import CheckinLinkService
from ian.application.events import EventService
from ian.application.member_notifications import MemberNotificationService
from ian.application.members import MemberService
from ian.application.notifications import NotificationSender, OperationalNotifier
from ian.application.rag import RagSearchPort, RagService
from ian.application.reminders import DailyReminderService
from ian.infrastructure.rag.adapter import HybridRagAdapter
from ian.infrastructure.payload_mcp.client import (
    McpToolCaller,
    StreamableHttpMcpToolCaller,
)
from ian.infrastructure.payload_mcp.event_repository import (
    PayloadMcpEventRepository,
)
from ian.infrastructure.payload_mcp.member_repository import (
    PayloadMcpMemberRepository,
)
from ian.infrastructure.notifications.adapters import (
    DiscordOperationalNotifier,
    PlatformNotificationSender,
)
from ian.infrastructure.notifications.discord import DiscordHttpClient
from ian.infrastructure.agent.langgraph import LangGraphAgentAdapter
from ian.infrastructure.chat_history import JsonlChatHistoryWriter


@dataclass(frozen=True)
class ApplicationServices:
    agent: AgentService
    chat_history: ChatHistoryService
    events: EventService
    members: MemberService
    checkins: CheckinLinkService
    reminders: DailyReminderService
    member_notifications: MemberNotificationService
    operational_notifications: OperationalNotifier
    rag: RagService


_default_application: ApplicationServices | None = None


def build_application(
    caller: McpToolCaller | None = None,
    notification_sender: NotificationSender | None = None,
    operational_notifier: OperationalNotifier | None = None,
    agent_adapter: AgentPort | None = None,
    rag_adapter: RagSearchPort | None = None,
    chat_history_writer: ChatHistoryWriter | None = None,
) -> ApplicationServices:
    """Compose application services without performing network I/O."""
    discord: DiscordHttpClient | None = None
    agent_log_channel_id = 0
    if caller is None:
        from ian.config import (
            NTUAI_MCP_API_KEY,
            NTUAI_MCP_TIMEOUT_SECONDS,
            NTUAI_MCP_URL,
        )

        caller = StreamableHttpMcpToolCaller(
            NTUAI_MCP_URL,
            NTUAI_MCP_API_KEY,
            NTUAI_MCP_TIMEOUT_SECONDS,
        )

    if (
        notification_sender is None
        or operational_notifier is None
        or agent_adapter is None
    ):
        from ian.config import (
            DISCORD_BOT_TOKEN,
            DISCORD_LOG_CHANNEL_ID,
            DISCORD_LOG_CHANNEL_ID_INT,
            LINE_CHANNEL_ACCESS_TOKEN,
            PAGE_ACCESS_TOKEN,
        )

        discord = DiscordHttpClient(DISCORD_BOT_TOKEN)
        agent_log_channel_id = DISCORD_LOG_CHANNEL_ID_INT
        if notification_sender is None:
            notification_sender = PlatformNotificationSender(
                discord,
                page_access_token=PAGE_ACCESS_TOKEN,
                line_channel_access_token=LINE_CHANNEL_ACCESS_TOKEN,
            )
        if operational_notifier is None:
            operational_notifier = DiscordOperationalNotifier(
                discord,
                bot_token=DISCORD_BOT_TOKEN,
                log_channel_id=DISCORD_LOG_CHANNEL_ID,
            )

    events = EventService(PayloadMcpEventRepository(caller))
    members = MemberService(PayloadMcpMemberRepository(caller))
    if agent_adapter is None:
        assert discord is not None
        agent_adapter = LangGraphAgentAdapter(discord, agent_log_channel_id)
    if rag_adapter is None:
        rag_adapter = HybridRagAdapter()
    if chat_history_writer is None:
        from ian.config import CHAT_HISTORY_FILE

        chat_history_writer = JsonlChatHistoryWriter(CHAT_HISTORY_FILE)
    return ApplicationServices(
        agent=AgentService(agent_adapter),
        chat_history=ChatHistoryService(chat_history_writer),
        events=events,
        members=members,
        checkins=CheckinLinkService(members),
        reminders=DailyReminderService(events, members, notification_sender),
        member_notifications=MemberNotificationService(
            events,
            members,
            notification_sender,
        ),
        operational_notifications=operational_notifier,
        rag=RagService(rag_adapter),
    )


def get_application() -> ApplicationServices:
    """Return the process-wide default application graph, built on first use."""
    global _default_application
    if _default_application is None:
        _default_application = build_application()
    return _default_application
