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

import json
from collections import deque
from datetime import datetime, timedelta, timezone

import pytest

from ian.services.event_mcp_repository import (
    EVENT_SELECT,
    EventMcpRepository,
)


TPE = timezone(timedelta(hours=8))


def event_document(event_id: int = 1, **overrides) -> dict:
    document = {
        "id": event_id,
        "title": f"Event {event_id}",
        "startDate": "2026-08-01T19:00:00+08:00",
        "endDate": "2026-08-01T21:00:00+08:00",
        "slug": f"event-{event_id}",
        "_status": "published",
    }
    document.update(overrides)
    return document


def mcp_text(*documents: dict) -> str:
    if not documents:
        return 'Collection: "events"\nFound 0 documents'
    return "\n".join(f"```json\n{json.dumps(document)}\n```" for document in documents)


class QueueCaller:
    def __init__(self, *responses: str):
        self.responses = deque(responses)
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, arguments))
        return self.responses.popleft()


@pytest.mark.asyncio
async def test_find_by_id_uses_event_allowlist_and_published_filter():
    caller = QueueCaller(mcp_text(event_document(42)))

    event = await EventMcpRepository(caller).find_by_id(42)

    assert event is not None
    assert event.id == 42
    tool, arguments = caller.calls[0]
    assert tool == "findEvents"
    assert arguments["depth"] == 0
    assert json.loads(arguments["select"]) == EVENT_SELECT
    assert "checkIns" not in json.loads(arguments["select"])
    assert json.loads(arguments["where"]) == {"_status": {"equals": "published"}}


@pytest.mark.asyncio
async def test_list_published_applies_utc_date_bounds_and_sorts_results():
    caller = QueueCaller(
        mcp_text(
            event_document(2, startDate="2026-08-01T20:00:00+08:00"),
            event_document(1, startDate="2026-08-01T19:00:00+08:00"),
        )
    )
    repository = EventMcpRepository(caller)

    events = await repository.list_published(
        starts_at_or_after=datetime(2026, 8, 1, tzinfo=TPE),
        starts_before=datetime(2026, 8, 2, tzinfo=TPE),
    )

    assert [event.id for event in events] == [1, 2]
    where = json.loads(caller.calls[0][1]["where"])
    assert where["_status"] == {"equals": "published"}
    assert where["startDate"] == {
        "greater_than_equal": "2026-07-31T16:00:00+00:00",
        "less_than": "2026-08-01T16:00:00+00:00",
    }


@pytest.mark.asyncio
async def test_list_published_fetches_following_page_after_full_page():
    first_page = [event_document(index) for index in range(1, 101)]
    caller = QueueCaller(mcp_text(*first_page), mcp_text(event_document(101)))

    events = await EventMcpRepository(caller).list_published()

    assert len(events) == 101
    assert [arguments["page"] for _, arguments in caller.calls] == [1, 2]


@pytest.mark.asyncio
async def test_repository_skips_invalid_documents_and_keeps_valid_events():
    caller = QueueCaller(
        mcp_text(event_document(1, title=" "), event_document(2))
    )

    events = await EventMcpRepository(caller).list_published()

    assert [event.id for event in events] == [2]
