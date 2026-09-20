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
from datetime import timedelta
from typing import Any, Protocol

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class PayloadMcpError(RuntimeError):
    """Base error for shared ntuai.dev Payload MCP operations."""


class PayloadMcpConfigurationError(PayloadMcpError):
    """Raised when the shared MCP client is not configured."""


class PayloadMcpTransportError(PayloadMcpError):
    """Raised when the MCP transport cannot complete a request."""


class PayloadMcpToolError(PayloadMcpError):
    """Raised when an MCP tool returns an error result."""


class PayloadMcpSchemaError(PayloadMcpError):
    """Raised when an MCP response violates the Payload text contract."""


class McpToolCaller(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str: ...


class StreamableHttpMcpToolCaller:
    """Execute one authenticated MCP tool call over Streamable HTTP."""

    def __init__(self, url: str, api_key: str, timeout_seconds: int = 20):
        self.url = url.strip()
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds

    def _require_config(self) -> None:
        if not self.url or not self.api_key:
            raise PayloadMcpConfigurationError("NTUAI_MCP_URL or NTUAI_MCP_API_KEY is not configured")
        if self.timeout_seconds <= 0:
            raise PayloadMcpConfigurationError("NTUAI_MCP_TIMEOUT_SECONDS must be positive")

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
                            read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
                        )
        except PayloadMcpError:
            raise
        except Exception as error:
            raise PayloadMcpTransportError(
                f"MCP tool {name} failed ({type(error).__name__})"
            ) from error

        if result.isError:
            raise PayloadMcpToolError(f"MCP tool {name} returned an error")

        text_parts = [
            item.text
            for item in result.content
            if getattr(item, "type", None) == "text" and hasattr(item, "text")
        ]
        if not text_parts:
            raise PayloadMcpSchemaError(f"MCP tool {name} returned no text content")
        return "\n".join(text_parts)


_JSON_FENCE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)


def parse_payload_documents(text: str) -> list[dict[str, Any]]:
    """Extract Payload documents from the MCP plugin's fenced JSON response."""
    documents: list[dict[str, Any]] = []
    for block in _JSON_FENCE.findall(text):
        try:
            value = json.loads(block)
        except json.JSONDecodeError as error:
            raise PayloadMcpSchemaError("MCP response contains invalid JSON") from error

        values = value if isinstance(value, list) else [value]
        if not all(isinstance(item, dict) for item in values):
            raise PayloadMcpSchemaError("MCP response JSON must contain documents")
        documents.extend(values)

    if documents:
        return documents
    if re.search(r"Found\s+0\s+document", text, re.IGNORECASE):
        return []
    raise PayloadMcpSchemaError("MCP response did not contain Payload documents")
