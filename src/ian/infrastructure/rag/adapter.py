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
from types import ModuleType

from ian.application.rag import RagSearchResult


class HybridRagAdapter:
    """Lazy adapter around the LangChain, FAISS, and BM25 runtime."""

    def __init__(self, alpha: float = 0.6):
        if not 0 <= alpha <= 1:
            raise ValueError("alpha must be between 0 and 1")
        self._alpha = alpha
        self._runtime: ModuleType | None = None

    def _load_runtime(self) -> ModuleType:
        if self._runtime is None:
            import ian.infrastructure.rag.runtime as runtime

            self._runtime = runtime
        return self._runtime

    def initialize(self) -> bool:
        return bool(self._load_runtime().initialize_rag_system())

    def is_initialized(self) -> bool:
        return bool(self._runtime and self._runtime.is_initialized())

    async def search(self, query: str, top_k: int) -> list[RagSearchResult]:
        runtime = self._load_runtime()
        results = await asyncio.to_thread(
            runtime.hybrid_search,
            query,
            top_k,
            self._alpha,
        )
        return [
            RagSearchResult(
                content=document.page_content,
                score=score,
                methods=methods,
                source=str(document.metadata.get("source", "unknown")),
                content_type=str(document.metadata.get("type", "")),
                tags=tuple(str(tag) for tag in document.metadata.get("tags", ())),
                entity_type=str(document.metadata.get("entity_type", "")),
                path=str(document.metadata.get("path", "")),
                section_title=str(document.metadata.get("section_title", "")),
            )
            for document, score, methods in results
        ]
