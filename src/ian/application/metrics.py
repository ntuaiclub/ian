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

from collections.abc import Mapping
from typing import Protocol


MetricAttributes = Mapping[str, str]

PLATFORMS = frozenset({"discord", "facebook", "line", "mcp", "webhook"})
OUTCOMES = frozenset(
    {
        "error",
        "failure",
        "ignored",
        "no_response",
        "not_ready",
        "rate_limited",
        "ready",
        "rejected",
        "success",
    }
)
MCP_TOOLS = frozenset(
    {
        "bind_email",
        "event_retriever",
        "notify_members",
        "notify_staff",
        "qa_retreviler",
        "update_personal_prompt",
        "update_subscribe",
    }
)
MEMBER_OPERATIONS = frozenset({"load"})
DEPENDENCIES = frozenset({"discord", "facebook", "line", "payload_mcp", "rag"})


class MetricSink(Protocol):
    def increment(
        self,
        name: str,
        value: int = 1,
        attributes: MetricAttributes | None = None,
    ) -> None: ...

    def observe(
        self,
        name: str,
        value: int | float,
        attributes: MetricAttributes | None = None,
    ) -> None: ...

    def set_value(
        self,
        name: str,
        value: int | float,
        attributes: MetricAttributes | None = None,
    ) -> None: ...


class NoOpMetricSink:
    def increment(
        self,
        name: str,
        value: int = 1,
        attributes: MetricAttributes | None = None,
    ) -> None:
        pass

    def observe(
        self,
        name: str,
        value: int | float,
        attributes: MetricAttributes | None = None,
    ) -> None:
        pass

    def set_value(
        self,
        name: str,
        value: int | float,
        attributes: MetricAttributes | None = None,
    ) -> None:
        pass


def _bounded(value: str, allowed: frozenset[str], label: str) -> str:
    normalized = value.strip().lower()
    if normalized not in allowed:
        raise ValueError(f"Unsupported metrics {label}: {value}")
    return normalized


class ApplicationMetrics:
    """Record Ian metrics through bounded, privacy-safe dimensions."""

    def __init__(self, sink: MetricSink):
        self.sink = sink

    def record_gateway_message(self, platform: str, outcome: str) -> None:
        self.sink.increment(
            "ian.gateway.messages",
            attributes={
                "platform": _bounded(platform, PLATFORMS, "platform"),
                "outcome": _bounded(outcome, OUTCOMES, "outcome"),
            },
        )

    def record_agent_call(self, outcome: str, duration_seconds: float) -> None:
        attributes = {"outcome": _bounded(outcome, OUTCOMES, "outcome")}
        self.sink.increment("ian.agent.calls", attributes=attributes)
        self.sink.observe(
            "ian.agent.call.duration",
            duration_seconds,
            attributes,
        )

    def record_mcp_tool(
        self,
        tool: str,
        outcome: str,
        duration_seconds: float,
    ) -> None:
        attributes = {
            "tool": _bounded(tool, MCP_TOOLS, "tool"),
            "outcome": _bounded(outcome, OUTCOMES, "outcome"),
        }
        self.sink.increment("ian.mcp.tool.calls", attributes=attributes)
        self.sink.observe(
            "ian.mcp.tool.duration",
            duration_seconds,
            attributes,
        )

    def record_reminder_run(
        self,
        outcome: str,
        duration_seconds: float,
        *,
        events_found: int,
        members_notified: int,
    ) -> None:
        attributes = {"outcome": _bounded(outcome, OUTCOMES, "outcome")}
        self.sink.increment("ian.reminder.runs", attributes=attributes)
        self.sink.observe("ian.reminder.run.duration", duration_seconds, attributes)
        self.sink.observe("ian.reminder.events", events_found)
        self.sink.observe("ian.reminder.members.notified", members_notified)

    def record_reminder_notification(self, platform: str, outcome: str) -> None:
        self.sink.increment(
            "ian.reminder.notifications",
            attributes={
                "platform": _bounded(platform, PLATFORMS, "platform"),
                "outcome": _bounded(outcome, OUTCOMES, "outcome"),
            },
        )

    def record_member_operation(
        self,
        operation: str,
        outcome: str,
        *,
        loaded_count: int | None = None,
    ) -> None:
        attributes = {
            "operation": _bounded(operation, MEMBER_OPERATIONS, "operation"),
            "outcome": _bounded(outcome, OUTCOMES, "outcome"),
        }
        self.sink.increment("ian.member.operations", attributes=attributes)
        if loaded_count is not None:
            self.sink.observe("ian.member.loaded", loaded_count, attributes)

    def record_rag_initialization(self, outcome: str) -> None:
        normalized = _bounded(outcome, OUTCOMES, "outcome")
        self.sink.increment(
            "ian.rag.initializations",
            attributes={"outcome": normalized},
        )
        self.sink.set_value(
            "ian.rag.initialized",
            1 if normalized == "success" else 0,
        )

    def record_rag_search(
        self,
        outcome: str,
        duration_seconds: float,
        *,
        result_count: int,
    ) -> None:
        attributes = {"outcome": _bounded(outcome, OUTCOMES, "outcome")}
        self.sink.increment("ian.rag.searches", attributes=attributes)
        self.sink.observe("ian.rag.search.duration", duration_seconds, attributes)
        self.sink.observe("ian.rag.search.results", result_count, attributes)

    def record_dependency_check(
        self,
        dependency: str,
        outcome: str,
        duration_seconds: float,
    ) -> None:
        attributes = {
            "dependency": _bounded(dependency, DEPENDENCIES, "dependency"),
            "outcome": _bounded(outcome, OUTCOMES, "outcome"),
        }
        self.sink.increment("ian.dependency.checks", attributes=attributes)
        self.sink.observe(
            "ian.dependency.check.duration",
            duration_seconds,
            attributes,
        )


NO_OP_METRICS = ApplicationMetrics(NoOpMetricSink())
