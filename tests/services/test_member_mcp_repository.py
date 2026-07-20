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
from datetime import datetime, timezone

import pytest

from ian.domain.members import Platform
from ian.services.member_mcp_repository import (
    DuplicateMemberError,
    MemberMcpRepository,
    MemberRepositoryError,
    MemberSchemaError,
    MemberTransportError,
    StreamableHttpMcpToolCaller,
    parse_payload_documents,
)


def mcp_text(*documents: dict) -> str:
    if not documents:
        return 'Collection: "users"\nFound 0 documents\nPage 1 of 1'
    blocks = "\n".join(
        f"```json\n{json.dumps(document)}\n```" for document in documents
    )
    return f'Collection: "users"\nFound {len(documents)} documents\nPage 1 of 1\n\n{blocks}'


def user_doc(user_id: int = 10) -> dict:
    return {
        "id": user_id,
        "name": "Test User",
        "email": "test@example.test",
        "emailVerified": True,
        "discord_acc_id": "discord-10",
        "fb_acc_id": None,
        "line_acc_id": None,
        "subscribe": "discord",
        "personal_prompt": None,
    }


def membership_doc(user_id: int = 10) -> dict:
    return {
        "id": 20,
        "user": user_id,
        "tier": 2,
        "start_at": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        "end_at": None,
    }


class QueueCaller:
    def __init__(self, *responses: str):
        self.responses = deque(responses)
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, arguments))
        return self.responses.popleft()


def test_parse_payload_documents_extracts_multiple_fenced_documents():
    assert parse_payload_documents(mcp_text({"id": 1}, {"id": 2})) == [
        {"id": 1},
        {"id": 2},
    ]


def test_parse_payload_documents_handles_empty_result():
    assert parse_payload_documents(mcp_text()) == []


@pytest.mark.parametrize("text", ["no json here", "```json\ninvalid\n```"])
def test_parse_payload_documents_rejects_invalid_contract(text):
    with pytest.raises(MemberSchemaError):
        parse_payload_documents(text)


def test_streamable_caller_requires_url_and_api_key():
    caller = StreamableHttpMcpToolCaller("", "", 20)

    with pytest.raises(MemberRepositoryError):
        caller._require_config()


@pytest.mark.asyncio
async def test_find_user_by_email_uses_whitelisted_fields_and_memberships():
    caller = QueueCaller(mcp_text(user_doc()), mcp_text(membership_doc()))
    repository = MemberMcpRepository(caller)

    user = await repository.find_user_by_email("test@example.test")

    assert user is not None
    assert user.id == 10
    assert user.memberships[0].tier == 2
    tool, arguments = caller.calls[0]
    assert tool == "findUsers"
    assert arguments["depth"] == 0
    assert json.loads(arguments["where"]) == {"email": {"equals": "test@example.test"}}
    selected = json.loads(arguments["select"])
    assert "account" not in selected
    assert "session" not in selected
    assert "banned" not in selected


@pytest.mark.asyncio
async def test_find_user_by_platform_rejects_duplicate_matches():
    caller = QueueCaller(mcp_text(user_doc(10), user_doc(11)))
    repository = MemberMcpRepository(caller)

    with pytest.raises(DuplicateMemberError):
        await repository.find_user_by_platform(Platform.DISCORD, "discord-10")


@pytest.mark.asyncio
async def test_update_user_rejects_non_whitelisted_fields_without_calling_mcp():
    caller = QueueCaller()
    repository = MemberMcpRepository(caller)

    with pytest.raises(MemberRepositoryError):
        await repository.update_user(10, {"role": "admin"})
    assert caller.calls == []


@pytest.mark.asyncio
async def test_update_user_calls_mcp_and_reads_back():
    updated_doc = {**user_doc(), "personal_prompt": "concise"}
    caller = QueueCaller(
        mcp_text(updated_doc),
        mcp_text(updated_doc),
        mcp_text(membership_doc()),
    )
    repository = MemberMcpRepository(caller)

    updated = await repository.update_user(10, {"personal_prompt": "concise"})

    assert updated.personal_prompt == "concise"
    assert caller.calls[0][0] == "updateUsers"
    assert caller.calls[0][1]["id"] == 10
    assert caller.calls[0][1]["personal_prompt"] == "concise"


@pytest.mark.asyncio
async def test_update_user_confirms_ambiguous_transport_failure_by_read_back():
    updated_doc = {**user_doc(), "discord_acc_id": "discord-new"}

    class AmbiguousCaller(QueueCaller):
        async def call_tool(self, name: str, arguments: dict) -> str:
            self.calls.append((name, arguments))
            if name == "updateUsers":
                raise MemberTransportError("connection lost after write")
            return self.responses.popleft()

    caller = AmbiguousCaller(mcp_text(updated_doc), mcp_text(membership_doc()))
    repository = MemberMcpRepository(caller)

    updated = await repository.update_user(10, {"discord_acc_id": "discord-new"})

    assert updated.discord_acc_id == "discord-new"


@pytest.mark.asyncio
async def test_update_user_preserves_transport_failure_when_read_back_differs():
    current_doc = {**user_doc(), "discord_acc_id": None}

    class FailedCaller(QueueCaller):
        async def call_tool(self, name: str, arguments: dict) -> str:
            self.calls.append((name, arguments))
            if name == "updateUsers":
                raise MemberTransportError("connection lost before write")
            return self.responses.popleft()

    caller = FailedCaller(mcp_text(current_doc), mcp_text(membership_doc()))
    repository = MemberMcpRepository(caller)

    with pytest.raises(MemberTransportError):
        await repository.update_user(10, {"discord_acc_id": "discord-new"})
