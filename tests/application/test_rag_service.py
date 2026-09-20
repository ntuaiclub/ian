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

import pytest

from ian.application.rag import RagSearchResult, RagService


class FakeRagAdapter:
    def __init__(self):
        self.initialized = False
        self.searches = []

    def initialize(self):
        self.initialized = True
        return True

    def is_initialized(self):
        return self.initialized

    async def search(self, query, top_k):
        self.searches.append((query, top_k))
        return [
            RagSearchResult(
                content="answer",
                score=0.75,
                methods="BM25+Semantic",
            )
        ]


@pytest.mark.asyncio
async def test_rag_service_delegates_lifecycle_and_search_to_port():
    adapter = FakeRagAdapter()
    service = RagService(adapter)

    assert service.is_initialized() is False
    assert service.initialize() is True
    assert service.is_initialized() is True

    results = await service.search("社課時間", top_k=3)

    assert adapter.searches == [("社課時間", 3)]
    assert results == [
        RagSearchResult(
            content="answer",
            score=0.75,
            methods="BM25+Semantic",
        )
    ]
