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

from types import SimpleNamespace

import pytest

from ian.application.rag import RagSearchResult
from ian.infrastructure.rag.adapter import HybridRagAdapter


class FakeRuntime:
    def __init__(self):
        self.initialized = False
        self.searches = []

    def initialize_rag_system(self):
        self.initialized = True
        return True

    def is_initialized(self):
        return self.initialized

    def hybrid_search(self, query, top_k, alpha):
        self.searches.append((query, top_k, alpha))
        document = SimpleNamespace(
            page_content="問題：社課時間？\n答案：星期四",
            metadata={
                "source": "faq",
                "type": "faq",
                "tags": ["社課", "時間"],
            },
        )
        return [(document, 0.8, "BM25+Semantic")]


def test_hybrid_rag_adapter_does_not_load_runtime_for_status_check():
    adapter = HybridRagAdapter()

    assert adapter.is_initialized() is False
    assert adapter._runtime is None


def test_hybrid_rag_adapter_initializes_runtime():
    adapter = HybridRagAdapter()
    runtime = FakeRuntime()
    adapter._runtime = runtime

    assert adapter.initialize() is True
    assert adapter.is_initialized() is True


@pytest.mark.asyncio
async def test_hybrid_rag_adapter_maps_langchain_documents_to_application_results():
    adapter = HybridRagAdapter(alpha=0.4)
    runtime = FakeRuntime()
    adapter._runtime = runtime

    results = await adapter.search("社課時間", 3)

    assert runtime.searches == [("社課時間", 3, 0.4)]
    assert results == [
        RagSearchResult(
            content="問題：社課時間？\n答案：星期四",
            score=0.8,
            methods="BM25+Semantic",
            source="faq",
            content_type="faq",
            tags=("社課", "時間"),
        )
    ]


@pytest.mark.parametrize("alpha", [-0.1, 1.1])
def test_hybrid_rag_adapter_rejects_invalid_weights(alpha):
    with pytest.raises(ValueError, match="alpha must be between 0 and 1"):
        HybridRagAdapter(alpha)
