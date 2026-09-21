# CONTRIBUTION.md

[繁體中文](CONTRIBUTION.md) | English

This document is a reference for contributors to this project. Before making changes, read the related files rather than relying only on this summary.

## Read these first

- [`ARCHITECTURE.md`](ARCHITECTURE.md): system architecture and core component notes.
- [`Makefile`](Makefile): common development, test, pre-commit, and Docker commands.
- [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/): bug / feature issue formats.
- [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md): required PR content and impact checklist.
- Related source and tests: when changing a module, read that module and its tests first.

## Project layers

- `src/ian/domain/`: I/O-free models and pure rules.
- `src/ian/application/`: use cases, DTOs, and application-owned Protocols.
- `src/ian/infrastructure/`: Payload MCP, notification, LangGraph, and Hybrid RAG concrete adapters/runtime.
- `src/ian/gateways/`: Discord, FB/LINE webhook, and FastMCP inbound adapters.
- `src/ian/entrypoints/`: Reminder scheduler and process supervisor; process lifecycle only.
- `src/ian/bootstrap.py`: the only dependency composition root.
- `tests/`: pytest tests, grouped by domain, application, adapter/gateway, and overall architecture rules.

Keep the dependency direction: `gateways/entrypoints -> application -> domain`. `infrastructure` implements application ports and is assembled only by `bootstrap.py`. Application must not import infrastructure, gateway, entrypoint, HTTP/MCP, or platform SDKs.

## Environment setup

This project uses Python 3.11 and `uv` for dependency management. First-time setup:

```bash
make setup
```

See `make help` for common commands.

## Environment variables

When you need local services or platform integrations, create `.env` first:

```bash
cp .env.example .env
```

Then fill in real values as needed. Main variables:

| Variable | Description |
|------|------|
| `DISCORD_BOT_TOKEN` | Discord Bot Token |
| `DISCORD_LOG_CHANNEL_ID` | Discord log channel ID |
| `STAFF_NOTIFICATION_CHANNEL_ID` | Staff notification channel ID |
| `GOOGLE_API_KEY` | Google Gemini API Key |
| `PAGE_ACCESS_TOKEN` | Facebook Page Access Token |
| `FB_VERIFY_TOKEN` | Facebook Webhook verification Token |
| `NTUAI_MCP_URL` | ntuai.dev Payload MCP endpoint |
| `NTUAI_MCP_API_KEY` | Events, Users, and Memberships MCP API Key |
| `NTUAI_MCP_TIMEOUT_SECONDS` | Payload MCP call timeout in seconds |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Channel Access Token |
| `LINE_CHANNEL_SECRET` | LINE Channel Secret |
| `LINE_ALLOWED_GROUPS` | LINE allowlisted group IDs (comma-separated) |
| `NGROK_AUTHTOKEN` | ngrok Auth Token |

Do not commit `.env`, API keys, tokens, private keys, personal data, or real user data.

## Local development

List existing CLI commands:

```bash
uv run ian --help
```

Common services can be started separately:

```bash
uv run ian serve
uv run ian mcp --port 5191
uv run ian webhook
uv run ian reminder --daemon
uv run ian discord
```

This project uses pre-commit for lightweight format, lint, and repository hygiene checks. First-time setup already installs the hooks. To run checks on all files manually:

```bash
make precommit
```

FAISS dependencies are pinned with platform markers in `pyproject.toml`: macOS installs `faiss-cpu`; Linux x86_64 / CUDA containers install `faiss-gpu-cu12`.

## Docker Compose

Docker Compose requires an NVIDIA GPU and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).

```bash
make docker-build
make docker-up
make docker-logs
make docker-down
```

The container starts services in order via `ian serve`:

1. Start the MCP Server (port 5191) and wait for the health check to pass (model load takes about 60-90 seconds).
2. Start the Flask Webhook Server (port 5190).
3. Start the Daily Event Reminder Daemon (automatic notification at 19:00 UTC+8 every day).
4. Start the Discord Bot.

## Contribution workflow

Before contributing, create a new branch from the latest main branch:

```bash
git switch main
git pull
git switch -c <type>/<short-description>
```

Preferred branch prefixes: `fix/`, `feat/`, `docs/`, `refactor/`, `test/`, or `chore/`.

For bugs or feature requests, open an issue first and use a template in [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/). When opening a PR, use [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md), link the related issue, and clearly describe how you tested and what is affected.

PR titles should follow the same prefixes as issue titles, for example:

- `[Bug]: fix Discord webhook retry handling`
- `[Feature]: add member subscription settings`
- `[Docs]: update local development guide`
- `[Refactor]: simplify reminder scheduling`
- `[Test]: cover URL validation edge cases`
- `[Chore]: update dependency lockfile`

## Development notes

- Prefer adding or updating tests, especially for `domain` pure logic, permission checks, URL validation, prompt injection, member role, and notification behavior.
- When changing Discord, Webhook, MCP, Reminder, or Docker behavior, document how you verified it in the PR Impact Checklist.
- When adding or changing environment variables, update `.env.example` and this document at the same time.
- Do not expose tokens, API keys, private keys, personal data, member data, or platform account IDs in logs, test fixtures, docs, or PRs.
- Tests against external APIs, Google Sheets, Discord, LINE, and Facebook should avoid real services; mock when possible.
- Changes related to RAG, FAISS, model loading, and platform webhooks can be environment-sensitive; include reproducible local or Docker verification steps.
- Keep commits and PRs focused; do not mix in unrelated formatting or refactors.
- If you encounter existing uncommitted changes, confirm their source first; do not overwrite or revert someone else's work.

## Verification

Before submitting a PR, at least confirm tests and pre-commit:

```bash
make test
make precommit
```

If you change Docker, startup flow, or platform integration, also verify the corresponding services using the `Makefile` and this document. If you could not run some checks, explain why and the risk in the PR Testing section.

## Collaboration guidelines

- Read the related files and tests before editing.
- Prefer existing architecture, naming, and test style.
- Change only files related to the task.
- After finishing, report the actual changes and the verification commands you ran.
