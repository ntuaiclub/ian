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
from typing import Protocol


@dataclass(frozen=True)
class RagSearchResult:
    """Technology-neutral search result returned to inbound adapters."""

    content: str
    score: float
    methods: str
    source: str = "unknown"
    content_type: str = ""
    tags: tuple[str, ...] = ()
    entity_type: str = ""
    path: str = ""
    section_title: str = ""


class RagSearchPort(Protocol):
    """Outbound port implemented by the concrete hybrid search adapter."""

    def initialize(self) -> bool: ...

    def is_initialized(self) -> bool: ...

    async def search(self, query: str, top_k: int) -> list[RagSearchResult]: ...


class RagService:
    """Application-facing entry point for knowledge-base retrieval."""

    def __init__(self, adapter: RagSearchPort):
        self.adapter = adapter

    def initialize(self) -> bool:
        return self.adapter.initialize()

    def is_initialized(self) -> bool:
        return self.adapter.is_initialized()

    async def search(self, query: str, top_k: int = 5) -> list[RagSearchResult]:
        return await self.adapter.search(query, top_k)
