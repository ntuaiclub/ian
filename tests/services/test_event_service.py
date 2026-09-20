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

from datetime import date, datetime, timedelta, timezone

import pytest

from ian.domain.events import Event
from ian.services.event_service import EventService


TPE = timezone(timedelta(hours=8))


def event(event_id: int, *, tier: int | None = None, title: str | None = None) -> Event:
    return Event.model_validate(
        {
            "id": event_id,
            "title": title or f"Event {event_id}",
            "startDate": "2026-08-01T19:00:00+08:00",
            "endDate": "2026-08-01T21:00:00+08:00",
            "minimumTier": tier,
            "speaker": "Ada",
            "slug": f"event-{event_id}",
            "_status": "published",
        }
    )


class FakeRepository:
    def __init__(self, events: list[Event]):
        self.events = events
        self.date_bounds: tuple[datetime | None, datetime | None] | None = None

    async def find_by_id(self, event_id: int) -> Event | None:
        return next((item for item in self.events if item.id == event_id), None)

    async def list_published(self, *, starts_at_or_after=None, starts_before=None):
        self.date_bounds = (starts_at_or_after, starts_before)
        return self.events


@pytest.mark.asyncio
async def test_get_event_hides_restricted_event_as_not_found():
    service = EventService(FakeRepository([event(1, tier=2)]))

    assert await service.get_event(1, viewer_tier=1) is None
    assert (await service.get_event(1, viewer_tier=2)).id == 1


@pytest.mark.asyncio
async def test_list_events_on_date_uses_taipei_half_open_boundary_and_tier():
    repository = FakeRepository([event(1), event(2, tier=3)])
    service = EventService(repository)

    events = await service.list_events_on_date(date(2026, 8, 1), viewer_tier=1)

    assert [item.id for item in events] == [1]
    assert repository.date_bounds == (
        datetime(2026, 8, 1, tzinfo=TPE),
        datetime(2026, 8, 2, tzinfo=TPE),
    )


@pytest.mark.asyncio
async def test_search_events_matches_structured_and_lexical_text():
    target = event(1, title="MCP Basics")
    target.content = {"root": {"children": [{"type": "paragraph", "children": [{"text": "Payload integration"}]}]}}
    service = EventService(FakeRepository([target, event(2, tier=2, title="Hidden")]))

    results = await service.search_events("payload", viewer_tier=1)

    assert [item.id for item in results] == [1]


def test_format_event_uses_taipei_details_and_omits_empty_optional_fields():
    message = EventService.format_event(event(1, title="Event MCP"))

    assert "Event MCP" in message
    assert "日期：2026-08-01 週六" in message
    assert "時間：19:00 - 21:00" in message
    assert "講者：Ada" in message
    assert "地點：" not in message
