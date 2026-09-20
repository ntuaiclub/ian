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

import ast
from pathlib import Path


SRC_ROOT = Path("src/ian")


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_domain_does_not_depend_on_outer_layers():
    forbidden = (
        "ian.application",
        "ian.bootstrap",
        "ian.config",
        "ian.gateways",
        "ian.infrastructure",
        "ian.services",
    )
    violations = []
    for path in sorted((SRC_ROOT / "domain").rglob("*.py")):
        for module in imported_modules(path):
            if module.startswith(forbidden):
                violations.append(f"{path}: {module}")

    assert violations == []


def test_application_does_not_depend_on_adapters_or_external_sdks():
    forbidden = (
        "ian.bootstrap",
        "ian.config",
        "ian.gateways",
        "ian.infrastructure",
        "ian.services",
        "discord",
        "httpx",
        "langchain",
        "linebot",
        "mcp",
        "requests",
    )
    violations = []
    for path in sorted((SRC_ROOT / "application").rglob("*.py")):
        for module in imported_modules(path):
            if module.startswith(forbidden):
                violations.append(f"{path}: {module}")

    assert violations == []


def test_infrastructure_does_not_depend_on_services_gateways_or_bootstrap():
    forbidden = (
        "ian.bootstrap",
        "ian.gateways",
        "ian.services",
    )
    violations = []
    for path in sorted((SRC_ROOT / "infrastructure").rglob("*.py")):
        for module in imported_modules(path):
            if module.startswith(forbidden):
                violations.append(f"{path}: {module}")

    assert violations == []


def test_concrete_adapters_are_only_composed_in_bootstrap():
    constructor_names = {
        "DiscordHttpClient",
        "DiscordOperationalNotifier",
        "HybridRagAdapter",
        "LangGraphAgentAdapter",
        "PayloadMcpEventRepository",
        "PayloadMcpMemberRepository",
        "PlatformNotificationSender",
        "StreamableHttpMcpToolCaller",
    }
    violations = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        if path == SRC_ROOT / "bootstrap.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in constructor_names:
                violations.append(f"{path}: {name}")

    assert violations == []


def test_legacy_service_and_gateway_modules_are_removed():
    legacy_paths = [
        SRC_ROOT / "services/agent",
        SRC_ROOT / "services/event_service.py",
        SRC_ROOT / "services/member_service.py",
        SRC_ROOT / "services/event_mcp_repository.py",
        SRC_ROOT / "services/member_mcp_repository.py",
        SRC_ROOT / "services/payload_mcp_client.py",
        SRC_ROOT / "services/notifications.py",
        SRC_ROOT / "services/discord_api.py",
        SRC_ROOT / "services/rag.py",
        SRC_ROOT / "gateways/agent_bridge.py",
    ]

    assert [str(path) for path in legacy_paths if path.exists()] == []


def test_gateways_do_not_import_payload_mcp_adapters():
    violations = []
    for path in sorted((SRC_ROOT / "gateways").rglob("*.py")):
        for module in imported_modules(path):
            if module.startswith("ian.infrastructure.payload_mcp"):
                violations.append(f"{path}: {module}")

    assert violations == []


def test_gateways_do_not_import_concrete_adapters():
    forbidden = (
        "ian.infrastructure.agent",
        "ian.infrastructure.notifications",
        "ian.infrastructure.rag",
        "ian.services",
    )
    violations = []
    for path in sorted((SRC_ROOT / "gateways").rglob("*.py")):
        for module in imported_modules(path):
            if module.startswith(forbidden):
                violations.append(f"{path}: {module}")

    assert violations == []
