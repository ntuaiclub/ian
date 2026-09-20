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
from collections import defaultdict
from typing import Any

from pydantic import ValidationError

from ian.domain.members import Membership, Platform, User
from ian.infrastructure.payload_mcp.client import (
    McpToolCaller,
    PayloadMcpError,
    PayloadMcpSchemaError,
    PayloadMcpTransportError,
    parse_payload_documents,
)


USER_SELECT = {
    "id": True,
    "name": True,
    "email": True,
    "emailVerified": True,
    "role": True,
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


class MemberRepositoryError(PayloadMcpError):
    """Base error for the remote Member repository."""


class MemberSchemaError(MemberRepositoryError):
    """Raised when a Member MCP document violates the contract."""


class MemberTransportError(MemberRepositoryError):
    """Raised when Member MCP transport fails."""


class DuplicateMemberError(MemberRepositoryError):
    """Raised when a supposedly unique member lookup returns multiple users."""


class PayloadMcpMemberRepository:
    """Typed adapter over the ntuai.dev Users and Memberships collections."""

    def __init__(self, caller: McpToolCaller):
        self.caller = caller

    async def _call_documents(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> list[dict[str, Any]]:
        try:
            text = await self.caller.call_tool(tool_name, arguments)
            return parse_payload_documents(text)
        except MemberRepositoryError:
            raise
        except PayloadMcpTransportError as error:
            raise MemberTransportError(str(error)) from error
        except PayloadMcpSchemaError as error:
            raise MemberSchemaError(str(error)) from error
        except PayloadMcpError as error:
            raise MemberRepositoryError(str(error)) from error

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
        transport_error: MemberTransportError | None = None
        try:
            await self._call_documents("updateUsers", arguments)
        except MemberTransportError as error:
            transport_error = error

        updated = await self.find_user_by_id(user_id)
        if updated is None:
            raise MemberSchemaError("updated user could not be read back")
        if transport_error is not None and any(
            getattr(updated, field) != value for field, value in fields.items()
        ):
            raise transport_error
        return updated
