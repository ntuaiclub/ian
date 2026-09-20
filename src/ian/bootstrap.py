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

from ian.application.checkins import CheckinLinkService
from ian.application.events import EventService
from ian.application.member_notifications import MemberNotificationService
from ian.application.members import MemberService
from ian.application.notifications import NotificationSender
from ian.application.reminders import DailyReminderService
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


@dataclass(frozen=True)
class ApplicationServices:
    events: EventService
    members: MemberService
    checkins: CheckinLinkService
    reminders: DailyReminderService
    member_notifications: MemberNotificationService


_default_application: ApplicationServices | None = None


def build_application(
    caller: McpToolCaller | None = None,
    notification_sender: NotificationSender | None = None,
) -> ApplicationServices:
    """Compose application services without performing network I/O."""
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

    if notification_sender is None:
        from ian.services.notifications import PlatformNotificationSender

        notification_sender = PlatformNotificationSender()

    events = EventService(PayloadMcpEventRepository(caller))
    members = MemberService(PayloadMcpMemberRepository(caller))
    return ApplicationServices(
        events=events,
        members=members,
        checkins=CheckinLinkService(members),
        reminders=DailyReminderService(events, members, notification_sender),
        member_notifications=MemberNotificationService(
            events,
            members,
            notification_sender,
        ),
    )


def get_application() -> ApplicationServices:
    """Return the process-wide default application graph, built on first use."""
    global _default_application
    if _default_application is None:
        _default_application = build_application()
    return _default_application
