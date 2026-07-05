from enum import Enum

import typer

app = typer.Typer(help="NTUAI Agent service entrypoints.")


class WebhookPlatform(str, Enum):
    all = "all"
    fb = "fb"
    line = "line"


def _run_mcp(http: bool = False, host: str = "0.0.0.0", port: int = 5191) -> None:
    from ian.gateways.mcp_server import entrypoint

    entrypoint(http=http, host=host, port=port)


def _run_webhook(platform: str = "all") -> None:
    from ian.gateways.webhook_server import entrypoint

    entrypoint(platform=platform)


def _run_reminder(target_date: str | None = None, dry: bool = False, daemon: bool = False) -> None:
    from ian.services.reminder_runner import daemon_loop, run_once

    if daemon:
        daemon_loop()
    else:
        run_once(target_date=target_date, dry=dry)


def _run_discord() -> None:
    from ian.gateways.discord_bot import entrypoint

    entrypoint()


def _run_serve(mcp_port: int = 5191, health_timeout: int = 90) -> None:
    from ian.services.service_supervisor import serve_all

    raise SystemExit(serve_all(mcp_port=mcp_port, health_timeout=health_timeout))


@app.command()
def mcp(
    http: bool = typer.Option(False, "--http", help="Run with Streamable HTTP transport."),
    host: str = typer.Option("0.0.0.0", "--host", help="HTTP server host."),
    port: int = typer.Option(5191, "--port", help="HTTP server port."),
) -> None:
    """Run the MCP tool server."""
    _run_mcp(http=http, host=host, port=port)


@app.command()
def webhook(
    platform: WebhookPlatform = typer.Option(
        WebhookPlatform.all,
        "--platform",
        help="Webhook routes to enable: all, fb, or line.",
    ),
) -> None:
    """Run the Facebook/LINE webhook server."""
    _run_webhook(platform=platform.value)


@app.command()
def reminder(
    daemon: bool = typer.Option(False, "--daemon", help="Run as daemon, trigger daily at 19:00 UTC+8."),
    dry: bool = typer.Option(False, "--dry", help="Dry run, no messages sent."),
    date: str | None = typer.Option(None, "--date", help="Check specific date (YYYY/MM/DD)."),
) -> None:
    """Run the daily event reminder."""
    _run_reminder(target_date=date, dry=dry, daemon=daemon)


@app.command()
def discord() -> None:
    """Run the Discord bot."""
    _run_discord()


@app.command()
def serve(
    mcp_port: int = typer.Option(5191, "--mcp-port", help="MCP HTTP server port."),
    health_timeout: int = typer.Option(90, "--health-timeout", help="Seconds to wait for MCP health."),
) -> None:
    """Run the full Ian service stack."""
    _run_serve(mcp_port=mcp_port, health_timeout=health_timeout)


if __name__ == "__main__":
    app()
