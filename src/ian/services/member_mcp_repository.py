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
import re
from collections import defaultdict
from datetime import timedelta
from typing import Any, Protocol

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError

from ian.domain.members import Membership, Platform, User


USER_SELECT = {
    "id": True,
    "name": True,
    "email": True,
    "emailVerified": True,
    "discord_acc_id": True,
    "fb_acc_id": True,
    "line_acc_id": True,
    "subscribe": True,
    "personal_prompt": True,
}
MEMBERSHIP_SELECT = {
    "id": True,
    "user": True,
    "tier": True,
    "start_at": True,
    "end_at": True,
}
UPDATABLE_USER_FIELDS = {
    "discord_acc_id",
    "fb_acc_id",
    "line_acc_id",
    "subscribe",
    "personal_prompt",
}
_JSON_FENCE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)


class MemberRepositoryError(RuntimeError):
    """Base error for the remote member repository."""


class MemberConfigurationError(MemberRepositoryError):
    """Raised when the MCP repository is not configured."""


class MemberTransportError(MemberRepositoryError):
    """Raised when the MCP transport cannot complete a request."""


class MemberToolError(MemberRepositoryError):
    """Raised when the remote MCP tool reports a failure."""


class MemberSchemaError(MemberRepositoryError):
    """Raised when the MCP response violates the member contract."""


class DuplicateMemberError(MemberRepositoryError):
    """Raised when a supposedly unique member lookup returns multiple users."""


class McpToolCaller(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str: ...


class StreamableHttpMcpToolCaller:
    """Execute one MCP tool call over authenticated Streamable HTTP."""

    def __init__(self, url: str, api_key: str, timeout_seconds: int = 20):
        self.url = url.strip()
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds

    def _require_config(self) -> None:
        if not self.url or not self.api_key:
            raise MemberConfigurationError(
                "MEMBER_MCP_URL or MEMBER_MCP_API_KEY is not configured"
            )
        if self.timeout_seconds <= 0:
            raise MemberConfigurationError(
                "MEMBER_MCP_TIMEOUT_SECONDS must be positive"
            )

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        self._require_config()
        timeout = httpx.Timeout(float(self.timeout_seconds))
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=timeout,
                follow_redirects=True,
            ) as http_client:
                async with streamable_http_client(
                    self.url,
                    http_client=http_client,
                ) as (read_stream, write_stream, _):
                    async with ClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
                    ) as session:
                        await session.initialize()
                        result = await session.call_tool(
                            name,
                            arguments,
                            read_timeout_seconds=timedelta(
                                seconds=self.timeout_seconds
                            ),
                        )
        except MemberRepositoryError:
            raise
        except Exception as error:
            raise MemberTransportError(
                f"MCP tool {name} failed ({type(error).__name__})"
            ) from error

        if result.isError:
            raise MemberToolError(f"MCP tool {name} returned an error")

        text_parts = [
            item.text
            for item in result.content
            if getattr(item, "type", None) == "text" and hasattr(item, "text")
        ]
        if not text_parts:
            raise MemberSchemaError(f"MCP tool {name} returned no text content")
        return "\n".join(text_parts)


def parse_payload_documents(text: str) -> list[dict[str, Any]]:
    """Extract Payload documents from the MCP plugin's fenced JSON response."""
    documents: list[dict[str, Any]] = []
    for block in _JSON_FENCE.findall(text):
        try:
            value = json.loads(block)
        except json.JSONDecodeError as error:
            raise MemberSchemaError("MCP response contains invalid JSON") from error

        values = value if isinstance(value, list) else [value]
        if not all(isinstance(item, dict) for item in values):
            raise MemberSchemaError("MCP response JSON must contain documents")
        documents.extend(values)

    if documents:
        return documents
    if re.search(r"Found\s+0\s+document", text, re.IGNORECASE):
        return []
    raise MemberSchemaError("MCP response did not contain Payload documents")


class MemberMcpRepository:
    """Typed repository over the ntuai.dev Payload MCP tools."""

    def __init__(self, caller: McpToolCaller):
        self.caller = caller

    async def _call_documents(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> list[dict[str, Any]]:
        text = await self.caller.call_tool(tool_name, arguments)
        return parse_payload_documents(text)

    @staticmethod
    def _parse_users(documents: list[dict[str, Any]]) -> list[User]:
        try:
            return [User.model_validate(document) for document in documents]
        except ValidationError as error:
            raise MemberSchemaError("MCP user response violates the schema") from error

    @staticmethod
    def _parse_memberships(documents: list[dict[str, Any]]) -> list[Membership]:
        try:
            return [Membership.model_validate(document) for document in documents]
        except ValidationError as error:
            raise MemberSchemaError(
                "MCP membership response violates the schema"
            ) from error

    async def _find_users(
        self,
        *,
        where: dict[str, Any] | None = None,
        user_id: int | None = None,
        limit: int = 2,
        page: int = 1,
    ) -> list[User]:
        arguments: dict[str, Any] = {
            "depth": 0,
            "limit": limit,
            "page": page,
            "select": json.dumps(USER_SELECT, separators=(",", ":")),
        }
        if where is not None:
            arguments["where"] = json.dumps(where, separators=(",", ":"))
        if user_id is not None:
            arguments["id"] = user_id
        documents = await self._call_documents("findUsers", arguments)
        return self._parse_users(documents)

    async def list_memberships(self, user_id: int | None = None) -> list[Membership]:
        page = 1
        limit = 100
        result: list[Membership] = []
        while True:
            arguments: dict[str, Any] = {
                "depth": 0,
                "limit": limit,
                "page": page,
                "select": json.dumps(MEMBERSHIP_SELECT, separators=(",", ":")),
            }
            if user_id is not None:
                arguments["where"] = json.dumps(
                    {"user": {"equals": user_id}},
                    separators=(",", ":"),
                )
            documents = await self._call_documents("findMemberships", arguments)
            memberships = self._parse_memberships(documents)
            result.extend(memberships)
            if len(memberships) < limit:
                return result
            page += 1

    async def _with_memberships(self, user: User | None) -> User | None:
        if user is None:
            return None
        memberships = await self.list_memberships(user.id)
        return user.model_copy(update={"memberships": memberships})

    @staticmethod
    def _unique_user(users: list[User], lookup: str) -> User | None:
        if len(users) > 1:
            raise DuplicateMemberError(f"multiple users matched {lookup}")
        return users[0] if users else None

    async def find_user_by_id(self, user_id: int) -> User | None:
        users = await self._find_users(user_id=user_id, limit=1)
        return await self._with_memberships(self._unique_user(users, "id"))

    async def find_user_by_email(self, email: str) -> User | None:
        users = await self._find_users(where={"email": {"equals": email}})
        return await self._with_memberships(self._unique_user(users, "email"))

    async def find_user_by_platform(
        self,
        platform: Platform,
        account_id: str,
    ) -> User | None:
        users = await self._find_users(
            where={platform.account_field: {"equals": account_id}}
        )
        return await self._with_memberships(
            self._unique_user(users, platform.account_field)
        )

    async def list_users_with_memberships(self) -> list[User]:
        page = 1
        limit = 100
        users: list[User] = []
        while True:
            batch = await self._find_users(limit=limit, page=page)
            users.extend(batch)
            if len(batch) < limit:
                break
            page += 1

        memberships_by_user: dict[int, list[Membership]] = defaultdict(list)
        for membership in await self.list_memberships():
            memberships_by_user[membership.user].append(membership)
        return [
            user.model_copy(
                update={"memberships": memberships_by_user.get(user.id, [])}
            )
            for user in users
        ]

    async def update_user(
        self,
        user_id: int,
        fields: dict[str, str | None],
    ) -> User:
        invalid = sorted(set(fields) - UPDATABLE_USER_FIELDS)
        if invalid:
            raise MemberRepositoryError(
                f"unsupported user update fields: {', '.join(invalid)}"
            )
        arguments: dict[str, Any] = {
            "id": user_id,
            "depth": 0,
            "select": json.dumps(USER_SELECT, separators=(",", ":")),
            **fields,
        }
        await self._call_documents("updateUsers", arguments)
        updated = await self.find_user_by_id(user_id)
        if updated is None:
            raise MemberSchemaError("updated user could not be read back")
        return updated
