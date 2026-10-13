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
from pathlib import Path
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_grafana_dashboard_uses_provisioned_prometheus_and_bounded_metrics():
    dashboard_path = (
        PROJECT_ROOT
        / "observability"
        / "grafana"
        / "dashboards"
        / "ian-overview.json"
    )
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))

    assert dashboard["uid"] == "ian-overview"
    assert dashboard["title"] == "Ian Overview"
    assert dashboard["panels"]
    assert all(
        panel["datasource"] == {"type": "prometheus", "uid": "prometheus"}
        for panel in dashboard["panels"]
    )

    expressions = {
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    }
    expected_metrics = (
        "ian_gateway_messages_total",
        "ian_agent_call_duration_seconds_bucket",
        "ian_mcp_tool_calls_total",
        "ian_dependency_checks_total",
        "ian_rag_initialized_ratio",
    )
    for metric in expected_metrics:
        assert any(metric in expression for expression in expressions)

    serialized = json.dumps(dashboard)
    private_selectors = (
        "account_id=",
        "channel_id=",
        "email=",
        "message=",
        "query=",
    )
    assert not any(selector in serialized for selector in private_selectors)


def test_observability_stack_is_optional_and_loopback_only():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert compose.count("profiles: [observability]") == 3
    assert 'GF_AUTH_ANONYMOUS_ENABLED: "false"' in compose

    resolved = json.loads(
        subprocess.check_output(
            [
                "docker",
                "compose",
                "--profile",
                "observability",
                "config",
                "--format",
                "json",
            ],
            cwd=PROJECT_ROOT,
            text=True,
        )
    )

    services = ("otel-collector", "prometheus", "grafana")
    ports = [
        port
        for name in services
        for port in resolved["services"][name].get("ports", [])
    ]
    assert len(ports) == 5
    assert all(port["host_ip"] == "127.0.0.1" for port in ports)
    assert "GF_SECURITY_ADMIN_PASSWORD" not in resolved["services"]["grafana"][
        "environment"
    ]

    collector = (PROJECT_ROOT / "observability" / "otel-collector.yml").read_text(
        encoding="utf-8"
    )
    assert "receivers: [otlp]" in collector
    assert "exporters: [prometheus]" in collector
    assert "resource_to_telemetry_conversion:" in collector

    prometheus = (PROJECT_ROOT / "observability" / "prometheus.yml").read_text(
        encoding="utf-8"
    )
    assert "otel-collector:8889" in prometheus
