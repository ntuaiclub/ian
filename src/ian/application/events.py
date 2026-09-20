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

from datetime import date, datetime, time, timedelta
from typing import Protocol

from ian.domain.events import Event, lexical_to_text
from ian.domain.time import TZ_TPE


class EventRepository(Protocol):
    async def find_by_id(self, event_id: int) -> Event | None: ...

    async def list_published(
        self,
        *,
        starts_at_or_after: datetime | None = None,
        starts_before: datetime | None = None,
    ) -> list[Event]: ...


class EventService:
    def __init__(self, repository: EventRepository):
        self.repository = repository

    @staticmethod
    def can_access(event: Event, viewer_tier: int) -> bool:
        return viewer_tier >= event.required_tier

    async def get_event(self, event_id: int, viewer_tier: int) -> Event | None:
        event = await self.repository.find_by_id(event_id)
        return event if event and self.can_access(event, viewer_tier) else None

    async def get_published_event_for_staff(self, event_id: int) -> Event | None:
        return await self.repository.find_by_id(event_id)

    async def list_events_on_date(
        self,
        target_date: date,
        viewer_tier: int,
    ) -> list[Event]:
        start = datetime.combine(target_date, time.min, tzinfo=TZ_TPE)
        end = start + timedelta(days=1)
        events = await self.repository.list_published(
            starts_at_or_after=start,
            starts_before=end,
        )
        return [event for event in events if self.can_access(event, viewer_tier)]

    async def list_upcoming_events(self, viewer_tier: int, limit: int = 3) -> list[Event]:
        now = datetime.now(TZ_TPE)
        events = await self.repository.list_published(starts_at_or_after=now)
        return [event for event in events if self.can_access(event, viewer_tier)][:limit]

    async def search_events(self, query: str, viewer_tier: int) -> list[Event]:
        normalized = query.strip().casefold()
        if not normalized:
            return await self.list_upcoming_events(viewer_tier)
        events = await self.repository.list_published()
        return [
            event
            for event in events
            if self.can_access(event, viewer_tier)
            and normalized in self._searchable_text(event)
        ]

    @staticmethod
    def _searchable_text(event: Event) -> str:
        values = [
            event.title,
            event.speaker,
            event.category,
            event.audience,
            event.location,
            lexical_to_text(event.content),
            event.notes,
            *(material.label for material in event.materials),
        ]
        return "\n".join(value for value in values if value).casefold()

    @staticmethod
    def format_event(event: Event) -> str:
        local_start = event.startDate.astimezone(TZ_TPE)
        local_end = event.endDate.astimezone(TZ_TPE)
        weekdays = ("週一", "週二", "週三", "週四", "週五", "週六", "週日")
        lines = [
            event.title,
            f"日期：{local_start:%Y-%m-%d} {weekdays[local_start.weekday()]}",
        ]
        lines.append(f"時間：{local_start:%H:%M} - {local_end:%H:%M}")
        fields = (
            ("地點", event.location),
            ("講者", event.speaker),
            ("類別", event.category),
            ("對象", event.audience),
            ("內容", lexical_to_text(event.content)),
        )
        lines.extend(f"{label}：{value}" for label, value in fields if value)
        flags = []
        if event.enableLivestream:
            flags.append("提供直播")
        if event.enableRecording:
            flags.append("預計錄影")
        if flags:
            lines.append(f"活動資訊：{' / '.join(flags)}")
        if event.nonMemberFee is not None:
            lines.append(f"非社員費用：{event.nonMemberFee}")
        if event.onlineURL:
            lines.append(f"線上連結：{event.onlineURL}")
        lines.extend(
            f"講義：{material.label} {material.url}" for material in event.materials
        )
        if event.videoURL:
            lines.append(f"錄影：{event.videoURL}")
        lines.extend(f"照片：{media.url}" for media in event.eventMedia)
        if event.notes:
            lines.append(f"備註：{event.notes}")
        return "\n".join(lines)

    @classmethod
    def format_events(cls, events: list[Event]) -> str:
        return "\n\n".join(cls.format_event(event) for event in events)
