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

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    MetricExporter,
    MetricExportResult,
    PeriodicExportingMetricReader,
)

from ian.infrastructure import metrics as metrics_module
from ian.infrastructure.metrics import (
    build_application_metrics,
    configure_metrics,
    get_in_memory_metric_reader,
)


def test_otel_sink_exports_counters_histograms_and_gauges_in_process():
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    metrics = build_application_metrics(provider.get_meter("ian.test"))

    metrics.record_gateway_message("discord", "success")
    metrics.record_agent_call("success", 0.25)
    metrics.record_rag_initialization("failure")

    data = reader.get_metrics_data()
    exported = {
        metric.name: metric
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }

    assert set(exported) == {
        "ian.agent.call.duration",
        "ian.agent.calls",
        "ian.gateway.messages",
        "ian.rag.initializations",
        "ian.rag.initialized",
    }
    gateway_point = exported["ian.gateway.messages"].data.data_points[0]
    assert gateway_point.value == 1
    assert dict(gateway_point.attributes) == {
        "platform": "discord",
        "outcome": "success",
    }
    rag_state = exported["ian.rag.initialized"].data.data_points[0]
    assert rag_state.value == 0

    provider.shutdown()


def test_configure_metrics_uses_in_memory_reader_without_backend(monkeypatch):
    monkeypatch.setattr(metrics_module, "_meter_provider", None)
    monkeypatch.setattr(metrics_module, "_in_memory_reader", None)
    monkeypatch.setattr(metrics_module.metrics, "set_meter_provider", lambda provider: None)

    provider = configure_metrics("ian-test", exporter="none")

    assert get_in_memory_metric_reader() is not None
    assert provider._sdk_config.resource.attributes["service.name"] == "ian-test"
    assert provider._sdk_config.resource.attributes["service.namespace"] == "ian"
    provider.shutdown()


def test_configure_metrics_rejects_unknown_exporter(monkeypatch):
    monkeypatch.setattr(metrics_module, "_meter_provider", None)

    try:
        configure_metrics("ian-test", exporter="private-backend")
    except ValueError as error:
        assert str(error) == "Unsupported OTEL_METRICS_EXPORTER: private-backend"
    else:
        raise AssertionError("unknown exporter must fail fast")


def test_exporter_failure_does_not_escape_metric_recording():
    class FailingExporter(MetricExporter):
        def export(self, metrics_data, timeout_millis=10_000, **kwargs):
            return MetricExportResult.FAILURE

        def force_flush(self, timeout_millis=10_000):
            return True

        def shutdown(self, timeout_millis=30_000, **kwargs):
            return None

    reader = PeriodicExportingMetricReader(
        FailingExporter(),
        export_interval_millis=float("inf"),
    )
    provider = MeterProvider(metric_readers=[reader])
    metrics = build_application_metrics(provider.get_meter("ian.test"))

    metrics.record_gateway_message("discord", "success")
    reader.collect()
    metrics.record_agent_call("success", 0.1)

    provider.shutdown()
