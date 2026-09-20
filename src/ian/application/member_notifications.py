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

from ian.application.events import EventService
from ian.application.members import MemberService
from ian.application.notifications import (
    DeliveryReport,
    NotificationSender,
    deliver_message,
)
from ian.domain.events import Event


class StaffPermissionError(PermissionError):
    """Raised before dependencies are called for a non-staff request."""


class EventNotFoundError(LookupError):
    """Raised when a published Event cannot be selected by ID."""


@dataclass(frozen=True)
class EventNotificationResult:
    event: Event
    delivery: DeliveryReport


class MemberNotificationService:
    def __init__(
        self,
        events: EventService,
        members: MemberService,
        sender: NotificationSender,
    ):
        self.events = events
        self.members = members
        self.sender = sender

    async def _require_staff(self, platform: str, account_id: str) -> None:
        if not await self.members.is_staff(platform, account_id):
            raise StaffPermissionError

    async def notify_event(
        self,
        platform: str,
        account_id: str,
        event_id: int,
        note: str = "",
    ) -> EventNotificationResult:
        await self._require_staff(platform, account_id)
        event = await self.events.get_published_event_for_staff(event_id)
        if event is None:
            raise EventNotFoundError(event_id)

        recipients = [
            recipient
            for recipient in await self.members.list_reminder_recipients()
            if self.events.can_access(event, int(recipient.tier))
        ]
        message = self.events.format_event(event)
        if note.strip():
            message += f"\n\n附註：{note.strip()}"
        delivery = await deliver_message(self.sender, recipients, message)
        return EventNotificationResult(event, delivery)

    async def notify_custom(
        self,
        platform: str,
        account_id: str,
        custom_message: str,
    ) -> DeliveryReport:
        await self._require_staff(platform, account_id)
        recipients = await self.members.list_reminder_recipients()
        message = f"NTUAI 通知\n\n{custom_message.strip()}"
        return await deliver_message(self.sender, recipients, message)

    async def list_upcoming(
        self,
        platform: str,
        account_id: str,
        limit: int = 3,
    ) -> list[Event]:
        await self._require_staff(platform, account_id)
        return await self.events.list_upcoming_events(viewer_tier=3, limit=limit)
