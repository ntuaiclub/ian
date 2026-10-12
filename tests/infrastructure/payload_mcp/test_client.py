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

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from ian.infrastructure.payload_mcp import client

from ian.infrastructure.payload_mcp.client import (
    PayloadMcpConfigurationError,
    PayloadMcpSchemaError,
    StreamableHttpMcpToolCaller,
    parse_payload_documents,
)


def test_parse_payload_documents_extracts_fenced_json_and_empty_results():
    assert parse_payload_documents('```json\n{"id": 1}\n```') == [{"id": 1}]
    assert parse_payload_documents('Found 0 documents') == []


def test_parse_payload_documents_extracts_multiple_fenced_documents():
    text = '```json\n{"id": 1}\n```\n```json\n{"id": 2}\n```'

    assert parse_payload_documents(text) == [{"id": 1}, {"id": 2}]


@pytest.mark.parametrize("text", ["not JSON", "```json\ninvalid\n```"])
def test_parse_payload_documents_rejects_invalid_text_contract(text):
    with pytest.raises(PayloadMcpSchemaError):
        parse_payload_documents(text)


def test_streamable_caller_requires_complete_shared_configuration():
    with pytest.raises(PayloadMcpConfigurationError):
        StreamableHttpMcpToolCaller("", "", 20)._require_config()


def test_streamable_caller_lists_tools_without_calling_application_tools(monkeypatch):
    calls = []

    class FakeHttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class FakeSession:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def initialize(self):
            calls.append("initialize")

        async def list_tools(self):
            calls.append("list_tools")
            return SimpleNamespace(
                tools=[SimpleNamespace(name="findUsers"), SimpleNamespace(name="findEvents")]
            )

        async def call_tool(self, *_args, **_kwargs):
            raise AssertionError("readiness must not call application tools")

    @asynccontextmanager
    async def fake_streamable_http_client(*_args, **_kwargs):
        yield object(), object(), None

    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **_kwargs: FakeHttpClient())
    monkeypatch.setattr(client, "streamable_http_client", fake_streamable_http_client)
    monkeypatch.setattr(client, "ClientSession", FakeSession)

    tools = asyncio.run(
        StreamableHttpMcpToolCaller(
            "https://example.test/mcp",
            "private-key",
            1,
        ).list_tools()
    )

    assert tools == {"findUsers", "findEvents"}
    assert calls == ["initialize", "list_tools"]
