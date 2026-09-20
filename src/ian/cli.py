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

from enum import Enum

import typer

app = typer.Typer(help="NTUAI Agent service commands.")


class WebhookPlatform(str, Enum):
    all = "all"
    fb = "fb"
    line = "line"


@app.command()
def mcp(
    host: str = typer.Option("0.0.0.0", "--host", help="HTTP server host."),
    port: int = typer.Option(5191, "--port", help="HTTP server port."),
) -> None:
    """Run the MCP server."""
    from ian.gateways.mcp_server import run_mcp_server

    run_mcp_server(host=host, port=port)


@app.command()
def webhook(
    platform: WebhookPlatform = typer.Option(
        WebhookPlatform.all,
        "--platform",
        help="Webhook routes to enable: all, fb, or line.",
    ),
) -> None:
    """Run the Facebook/LINE webhook server."""
    from ian.gateways.webhook_server import run_webhook_server

    run_webhook_server(platform=platform.value)


@app.command()
def reminder(
    daemon: bool = typer.Option(False, "--daemon", help="Run as daemon, trigger daily at 19:00 UTC+8."),
    dry: bool = typer.Option(False, "--dry", help="Dry run, no messages sent."),
    date: str | None = typer.Option(None, "--date", help="Check specific date (YYYY/MM/DD)."),
) -> None:
    """Run the daily event reminder."""
    from ian.entrypoints.reminder import daemon_loop, run_once

    if daemon:
        daemon_loop()
    else:
        run_once(target_date=date, dry=dry)


@app.command()
def discord() -> None:
    """Run the Discord bot."""
    from ian.gateways.discord_bot import run_discord_bot

    run_discord_bot()


@app.command()
def serve(
    mcp_port: int = typer.Option(5191, "--mcp-port", help="MCP HTTP server port."),
    health_timeout: int = typer.Option(90, "--health-timeout", help="Seconds to wait for MCP health."),
) -> None:
    """Run the full Ian service stack."""
    from ian.entrypoints.supervisor import serve_all

    raise SystemExit(serve_all(mcp_port=mcp_port, health_timeout=health_timeout))


if __name__ == "__main__":
    app()
