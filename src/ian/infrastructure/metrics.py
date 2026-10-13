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

import threading
from typing import Any

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.metrics.view import (
    ExplicitBucketHistogramAggregation,
    View,
)

from ian.application.metrics import ApplicationMetrics, MetricAttributes


INSTRUMENTS = {
    "ian.gateway.messages": ("counter", "{message}", "Gateway messages"),
    "ian.agent.calls": ("counter", "{call}", "Agent calls"),
    "ian.agent.call.duration": ("histogram", "s", "Agent call duration"),
    "ian.mcp.tool.calls": ("counter", "{call}", "MCP tool calls"),
    "ian.mcp.tool.duration": ("histogram", "s", "MCP tool call duration"),
    "ian.reminder.runs": ("counter", "{run}", "Reminder runs"),
    "ian.reminder.run.duration": ("histogram", "s", "Reminder run duration"),
    "ian.reminder.events": ("histogram", "{event}", "Events found per run"),
    "ian.reminder.members.notified": (
        "histogram",
        "{member}",
        "Members notified per run",
    ),
    "ian.reminder.notifications": (
        "counter",
        "{notification}",
        "Reminder notifications",
    ),
    "ian.member.operations": ("counter", "{operation}", "Member operations"),
    "ian.member.loaded": ("histogram", "{member}", "Members loaded"),
    "ian.rag.initializations": ("counter", "{attempt}", "RAG initialization attempts"),
    "ian.rag.initialized": ("gauge", "1", "RAG initialization state"),
    "ian.rag.searches": ("counter", "{search}", "RAG searches"),
    "ian.rag.search.duration": ("histogram", "s", "RAG search duration"),
    "ian.rag.search.results": ("histogram", "{result}", "RAG results per search"),
    "ian.dependency.checks": ("counter", "{check}", "Dependency checks"),
    "ian.dependency.check.duration": (
        "histogram",
        "s",
        "Dependency check duration",
    ),
}

_meter_provider: MeterProvider | None = None
_in_memory_reader: InMemoryMetricReader | None = None

_DURATION_HISTOGRAMS = (
    "ian.agent.call.duration",
    "ian.mcp.tool.duration",
    "ian.reminder.run.duration",
    "ian.rag.search.duration",
    "ian.dependency.check.duration",
)
_DURATION_BOUNDARIES = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1,
    2.5,
    5,
    10,
    30,
    60,
)
_METRIC_VIEWS = tuple(
    View(
        instrument_name=name,
        aggregation=ExplicitBucketHistogramAggregation(_DURATION_BOUNDARIES),
    )
    for name in _DURATION_HISTOGRAMS
)


class OpenTelemetryMetricSink:
    def __init__(self, meter: Meter):
        self.meter = meter
        self._instruments: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _instrument(self, name: str) -> Any:
        instrument = self._instruments.get(name)
        if instrument is not None:
            return instrument

        try:
            kind, unit, description = INSTRUMENTS[name]
        except KeyError as error:
            raise ValueError(f"Unknown Ian metric: {name}") from error

        with self._lock:
            instrument = self._instruments.get(name)
            if instrument is None:
                factory = {
                    "counter": self.meter.create_counter,
                    "gauge": self.meter.create_gauge,
                    "histogram": self.meter.create_histogram,
                }[kind]
                instrument = factory(name, unit=unit, description=description)
                self._instruments[name] = instrument
        return instrument

    def increment(
        self,
        name: str,
        value: int = 1,
        attributes: MetricAttributes | None = None,
    ) -> None:
        instrument = self._instrument(name)
        if INSTRUMENTS[name][0] != "counter":
            raise TypeError(f"Metric is not a counter: {name}")
        instrument.add(value, attributes)

    def observe(
        self,
        name: str,
        value: int | float,
        attributes: MetricAttributes | None = None,
    ) -> None:
        instrument = self._instrument(name)
        if INSTRUMENTS[name][0] != "histogram":
            raise TypeError(f"Metric is not a histogram: {name}")
        instrument.record(value, attributes)

    def set_value(
        self,
        name: str,
        value: int | float,
        attributes: MetricAttributes | None = None,
    ) -> None:
        instrument = self._instrument(name)
        if INSTRUMENTS[name][0] != "gauge":
            raise TypeError(f"Metric is not a gauge: {name}")
        instrument.set(value, attributes)


def build_application_metrics(meter: Meter | None = None) -> ApplicationMetrics:
    selected_meter = meter or metrics.get_meter("ian", "0.0.0")
    return ApplicationMetrics(OpenTelemetryMetricSink(selected_meter))


def configure_metrics(
    service_name: str,
    *,
    exporter: str = "none",
    endpoint: str = "http://localhost:4317",
    export_interval_millis: int = 60_000,
) -> MeterProvider:
    """Configure one process-wide provider without requiring a backend."""
    global _in_memory_reader, _meter_provider
    if _meter_provider is not None:
        return _meter_provider

    normalized_exporter = exporter.strip().lower()
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "ian",
        }
    )
    if normalized_exporter == "none":
        _in_memory_reader = InMemoryMetricReader()
        readers = [_in_memory_reader]
    elif normalized_exporter == "otlp":
        otlp_exporter = OTLPMetricExporter(
            endpoint=endpoint,
            insecure=endpoint.startswith("http://"),
        )
        readers = [
            PeriodicExportingMetricReader(
                otlp_exporter,
                export_interval_millis=export_interval_millis,
            )
        ]
    else:
        raise ValueError(f"Unsupported OTEL_METRICS_EXPORTER: {exporter}")

    provider = MeterProvider(
        resource=resource,
        metric_readers=readers,
        views=_METRIC_VIEWS,
    )
    metrics.set_meter_provider(provider)
    _meter_provider = provider
    return provider


def get_in_memory_metric_reader() -> InMemoryMetricReader | None:
    return _in_memory_reader
