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

from ian.application.metrics import ApplicationMetrics


class RecordingSink:
    def __init__(self):
        self.records = []

    def increment(self, name, value=1, attributes=None):
        self.records.append(("increment", name, value, attributes))

    def observe(self, name, value, attributes=None):
        self.records.append(("observe", name, value, attributes))

    def set_value(self, name, value, attributes=None):
        self.records.append(("set_value", name, value, attributes))


def test_application_metrics_records_bounded_tool_metrics():
    sink = RecordingSink()
    metrics = ApplicationMetrics(sink)

    metrics.record_mcp_tool("event_retriever", "success", 0.25)

    assert sink.records == [
        (
            "increment",
            "ian.mcp.tool.calls",
            1,
            {"tool": "event_retriever", "outcome": "success"},
        ),
        (
            "observe",
            "ian.mcp.tool.duration",
            0.25,
            {"tool": "event_retriever", "outcome": "success"},
        ),
    ]


def test_application_metrics_records_rag_state_and_search_results():
    sink = RecordingSink()
    metrics = ApplicationMetrics(sink)

    metrics.record_rag_initialization("success")
    metrics.record_rag_search("success", 0.1, result_count=3)

    assert ("set_value", "ian.rag.initialized", 1, None) in sink.records
    assert (
        "observe",
        "ian.rag.search.results",
        3,
        {"outcome": "success"},
    ) in sink.records


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("record_gateway_message", ("private-user-id", "success")),
        ("record_agent_call", ("private-error-text", 0.1)),
        ("record_mcp_tool", ("dynamic-private-tool", "success", 0.1)),
    ],
)
def test_application_metrics_rejects_unbounded_dimensions(method, args):
    metrics = ApplicationMetrics(RecordingSink())

    with pytest.raises(ValueError, match="Unsupported metrics"):
        getattr(metrics, method)(*args)
