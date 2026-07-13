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

import asyncio
import json

from ian.services.agent import callbacks, sessions, usage


def test_agent_callbacks_redact_tool_payloads_and_error_messages(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        callbacks,
        "add_log",
        lambda log_type, **fields: recorded.append({"type": log_type, **fields}),
    )
    handler = callbacks.DiscordLogCallbackHandler()

    handler.on_tool_start({"name": "lookup"}, "private tool arguments")
    handler.on_tool_end("private tool result", name="lookup")
    handler.on_tool_error(RuntimeError("private error detail"))

    assert recorded == [
        {
            "type": "TOOL_CALL",
            "tool_name": "lookup",
            "args": "[REDACTED content_length=22]",
        },
        {
            "type": "TOOL_RESULT",
            "tool_name": "lookup",
            "result": "[REDACTED content_length=19]",
        },
        {
            "type": "ERROR",
            "error": "RuntimeError",
            "context": "Tool execution",
        },
    ]
    assert handler.tool_results == ["private tool result"]


def test_usage_logs_counts_without_exposing_user_id(monkeypatch, capsys):
    monkeypatch.setattr(usage, "usage_tracker", {})
    monkeypatch.setattr(usage, "DAILY_LIMIT", 2)

    assert usage.check_and_update_usage("private-user-id") is True
    assert usage.check_and_update_usage("private-user-id") is True
    assert usage.check_and_update_usage("private-user-id") is False

    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [entry["event"] for entry in entries] == [
        "usage_updated",
        "usage_updated",
        "usage_limit_reached",
    ]
    assert [entry["usage_count"] for entry in entries] == [1, 2, 2]
    assert "private-user-id" not in json.dumps(entries)


def test_session_lifecycle_logs_without_exposing_identity(monkeypatch, capsys):
    monkeypatch.setattr(sessions, "sessions", {})

    _session, created = sessions.upsert_session(
        "private-session-id",
        "Private Name",
        "member",
        "private-channel-id",
        1.0,
    )
    sessions.clear_session_if_timeout(
        "private-session-id", 1.0 + sessions.TIMEOUT_SECONDS + 1
    )
    asyncio.run(sessions.clear_session("private-session-id"))

    assert created is True
    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [entry["event"] for entry in entries] == [
        "session_created",
        "session_expired",
        "session_clear_skipped",
    ]
    serialized = json.dumps(entries)
    for sensitive in ("private-session-id", "Private Name", "private-channel-id"):
        assert sensitive not in serialized
