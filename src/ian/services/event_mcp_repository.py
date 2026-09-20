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
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from ian.domain.events import Event
from ian.services.payload_mcp_client import (
    McpToolCaller,
    PayloadMcpConfigurationError,
    PayloadMcpSchemaError,
    PayloadMcpToolError,
    PayloadMcpTransportError,
    parse_payload_documents,
)
from ian.utils.logging import log_event


EVENT_SELECT = {
    "id": True,
    "title": True,
    "startDate": True,
    "endDate": True,
    "location": True,
    "content": True,
    "minimumTier": True,
    "materials": True,
    "videoURL": True,
    "eventMedia": True,
    "slug": True,
    "_status": True,
}


class EventRepositoryError(RuntimeError):
    """Base error for the remote Event repository."""


class EventConfigurationError(EventRepositoryError):
    """Raised when the Event MCP client is not configured."""


class EventTransportError(EventRepositoryError):
    """Raised when Event MCP transport fails."""


class EventToolError(EventRepositoryError):
    """Raised when the Event MCP tool returns an error."""


class EventSchemaError(EventRepositoryError):
    """Raised when an Event MCP document violates the contract."""


class EventMcpRepository:
    """Typed, read-only repository over the ntuai.dev Events collection."""

    def __init__(self, caller: McpToolCaller):
        self.caller = caller

    async def _call_documents(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            text = await self.caller.call_tool("findEvents", arguments)
            return parse_payload_documents(text)
        except PayloadMcpConfigurationError as error:
            raise EventConfigurationError(str(error)) from error
        except PayloadMcpTransportError as error:
            raise EventTransportError(str(error)) from error
        except PayloadMcpToolError as error:
            raise EventToolError(str(error)) from error
        except PayloadMcpSchemaError as error:
            raise EventSchemaError(str(error)) from error

    @staticmethod
    def _parse_events(documents: list[dict[str, Any]]) -> list[Event]:
        events: list[Event] = []
        for document in documents:
            try:
                events.append(Event.model_validate(document))
            except ValidationError as error:
                log_event(
                    "event_schema_skipped",
                    "event_mcp_repository",
                    level="warning",
                    status="invalid_document",
                    event_id=document.get("id"),
                    schema_error_kind=type(error).__name__,
                )
        return events

    @staticmethod
    def _base_arguments() -> dict[str, Any]:
        return {
            "depth": 0,
            "select": json.dumps(EVENT_SELECT, separators=(",", ":")),
        }

    async def find_by_id(self, event_id: int) -> Event | None:
        arguments = {
            **self._base_arguments(),
            "id": event_id,
            "where": json.dumps(
                {"_status": {"equals": "published"}},
                separators=(",", ":"),
            ),
            "limit": 1,
            "page": 1,
        }
        events = self._parse_events(await self._call_documents(arguments))
        published = [event for event in events if event.status == "published"]
        if len(published) > 1:
            raise EventSchemaError("findEvents returned multiple documents for one id")
        return published[0] if published else None

    async def list_published(
        self,
        *,
        starts_at_or_after: datetime | None = None,
        starts_before: datetime | None = None,
    ) -> list[Event]:
        where: dict[str, Any] = {"_status": {"equals": "published"}}
        if starts_at_or_after is not None:
            where["startDate"] = {
                "greater_than_equal": starts_at_or_after.astimezone(timezone.utc).isoformat()
            }
        if starts_before is not None:
            where.setdefault("startDate", {})["less_than"] = starts_before.astimezone(
                timezone.utc
            ).isoformat()

        page = 1
        limit = 100
        events: list[Event] = []
        while True:
            arguments = {
                **self._base_arguments(),
                "where": json.dumps(where, separators=(",", ":")),
                "limit": limit,
                "page": page,
            }
            batch = self._parse_events(await self._call_documents(arguments))
            events.extend(batch)
            if len(batch) < limit:
                return sorted(events, key=lambda event: (event.startDate, event.id))
            page += 1
