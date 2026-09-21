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
from datetime import date
from typing import Literal

from ian.application.events import EventService
from ian.application.members import MemberService
from ian.application.notifications import DeliveryReport, NotificationSender


class ReminderLoadError(RuntimeError):
    def __init__(self, stage: Literal["load_events", "load_members"], cause: Exception):
        super().__init__(str(cause))
        self.stage = stage
        self.__cause__ = cause


@dataclass(frozen=True)
class ReminderRunResult:
    status: Literal["no_events", "dry_run", "completed"]
    event_titles: tuple[str, ...]
    recipient_count: int
    delivery: DeliveryReport | None = None

    @property
    def event_count(self) -> int:
        return len(self.event_titles)


class DailyReminderService:
    def __init__(
        self,
        events: EventService,
        members: MemberService,
        sender: NotificationSender,
    ):
        self.events = events
        self.members = members
        self.sender = sender

    async def run(self, target_date: date, *, dry: bool = False) -> ReminderRunResult:
        try:
            events = await self.events.list_events_on_date(target_date, viewer_tier=3)
        except Exception as error:
            raise ReminderLoadError("load_events", error) from error

        titles = tuple(event.title for event in events)
        if not events:
            return ReminderRunResult("no_events", titles, 0)

        try:
            recipients = await self.members.list_reminder_recipients()
        except Exception as error:
            raise ReminderLoadError("load_members", error) from error

        deliveries = []
        for recipient in recipients:
            visible_events = [
                event
                for event in events
                if self.events.can_access(event, int(recipient.tier))
            ]
            if not visible_events:
                continue

            message = self.events.format_events(visible_events)
            deliveries.append((recipient, message))

        if dry:
            return ReminderRunResult("dry_run", titles, len(deliveries))

        delivery = DeliveryReport.for_recipients(
            [recipient for recipient, _message in deliveries]
        )
        for recipient, message in deliveries:
            try:
                success = await self.sender.send(recipient, message)
            except Exception:
                success = False
            delivery.record(recipient, success)

        return ReminderRunResult(
            "completed",
            titles,
            len(deliveries),
            delivery,
        )
