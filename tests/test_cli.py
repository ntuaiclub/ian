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

import sys
from types import SimpleNamespace

from typer.testing import CliRunner

from ian import cli


runner = CliRunner()


def test_cli_lists_service_commands():
    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    assert "mcp" in result.output
    assert "webhook" in result.output
    assert "reminder" in result.output
    assert "discord" in result.output
    assert "serve" in result.output


def test_mcp_command_delegates_to_app(monkeypatch):
    calls = []

    def fake_main(host="0.0.0.0", port=5191):
        calls.append({"host": host, "port": port})

    monkeypatch.setitem(
        sys.modules,
        "ian.gateways.mcp_server",
        SimpleNamespace(run_mcp_server=fake_main),
    )

    result = runner.invoke(
        cli.app,
        [
            "mcp",
            "--host",
            "127.0.0.1",
            "--port",
            "6000",
        ],
    )

    assert result.exit_code == 0
    assert calls == [{"host": "127.0.0.1", "port": 6000}]


def test_reminder_command_delegates_to_app(monkeypatch):
    calls = []

    def fake_main(target_date=None, dry=False, daemon=False):
        calls.append({"target_date": target_date, "dry": dry, "daemon": daemon})

    monkeypatch.setitem(
        sys.modules,
        "ian.services.reminder_runner",
        SimpleNamespace(
            run_once=fake_main,
            daemon_loop=lambda: fake_main(daemon=True),
        ),
    )

    result = runner.invoke(cli.app, ["reminder", "--dry", "--date", "2026/03/07"])

    assert result.exit_code == 0
    assert calls == [{"target_date": "2026/03/07", "dry": True, "daemon": False}]


def test_reminder_daemon_command_delegates_to_daemon_loop(monkeypatch):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "ian.services.reminder_runner",
        SimpleNamespace(
            run_once=lambda **_kwargs: calls.append("once"),
            daemon_loop=lambda: calls.append("daemon"),
        ),
    )

    result = runner.invoke(cli.app, ["reminder", "--daemon"])

    assert result.exit_code == 0
    assert calls == ["daemon"]


def test_serve_command_delegates_to_app(monkeypatch):
    calls = []

    def fake_main(mcp_port=5191, health_timeout=90):
        calls.append({"mcp_port": mcp_port, "health_timeout": health_timeout})
        return 0

    monkeypatch.setitem(
        sys.modules,
        "ian.services.service_supervisor",
        SimpleNamespace(serve_all=fake_main),
    )

    result = runner.invoke(cli.app, ["serve", "--mcp-port", "6001", "--health-timeout", "10"])

    assert result.exit_code == 0
    assert calls == [{"mcp_port": 6001, "health_timeout": 10}]


def test_webhook_command_accepts_valid_platform(monkeypatch):
    calls = []

    def fake_main(platform="all"):
        calls.append({"platform": platform})

    monkeypatch.setitem(
        sys.modules,
        "ian.gateways.webhook_server",
        SimpleNamespace(run_webhook_server=fake_main),
    )

    result = runner.invoke(cli.app, ["webhook", "--platform", "line"])

    assert result.exit_code == 0
    assert calls == [{"platform": "line"}]


def test_webhook_command_rejects_unknown_platform(monkeypatch):
    result = runner.invoke(cli.app, ["webhook", "--platform", "slack"])

    assert result.exit_code == 2


def test_discord_command_delegates_to_bot_runner(monkeypatch):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "ian.gateways.discord_bot",
        SimpleNamespace(run_discord_bot=lambda: calls.append("discord")),
    )

    result = runner.invoke(cli.app, ["discord"])

    assert result.exit_code == 0
    assert calls == ["discord"]
