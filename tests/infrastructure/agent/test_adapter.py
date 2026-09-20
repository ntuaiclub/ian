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

from types import SimpleNamespace

import pytest

from ian.application.agent import AgentRequest
from ian.infrastructure.agent import langgraph
from ian.infrastructure.agent import runtime


class FakeDiscord:
    def send_channel_message(self, channel_id, message):
        raise AssertionError("adapter construction must not send Discord messages")


@pytest.mark.asyncio
async def test_langgraph_adapter_maps_request_to_runtime(monkeypatch):
    calls = []
    logging = SimpleNamespace(
        configure_discord_logging=lambda discord, channel: calls.append(
            ("configure", discord, channel)
        )
    )
    monkeypatch.setattr(
        langgraph,
        "_load_logging",
        lambda: logging,
    )

    async def chat(*args, **kwargs):
        calls.append(("chat", args, kwargs))
        return "agent response"

    runtime_module = SimpleNamespace(
        start_dispatcher=lambda name, current_time: calls.append(
            ("start", name, current_time)
        ),
        chat_with_agent=chat,
    )
    monkeypatch.setattr(langgraph, "_load_runtime", lambda: runtime_module)
    discord = FakeDiscord()
    adapter = langgraph.LangGraphAgentAdapter(discord, 123)
    request = AgentRequest(
        session_id="session-1",
        user_name="User",
        question="Question",
        user_role=["社員"],
        timestamp=456.0,
        channel_id="channel-1",
        platform="Discord",
        account_id="account-1",
    )

    assert calls == []

    result = await adapter.generate(request)

    assert result == "agent response"
    assert calls[0] == ("configure", discord, 123)
    assert calls[1] == ("start", "User", {"timestamp": 456.0})
    assert calls[2][1][:6] == (
        "session-1",
        "User",
        "Question",
        ["社員"],
        456.0,
        "channel-1",
    )
    assert calls[2][2] == {
        "platform": "Discord",
        "account_id": "account-1",
        "member": None,
    }


@pytest.mark.asyncio
async def test_langgraph_adapter_delegates_clear_and_startup(monkeypatch):
    calls = []
    logging = SimpleNamespace(
        configure_discord_logging=lambda discord, channel: calls.append(
            ("configure", discord, channel)
        ),
        start_log_processor=lambda: calls.append(("start_logs",)),
        send_startup_notification=lambda: calls.append(("startup_notification",)),
    )
    monkeypatch.setattr(langgraph, "_load_logging", lambda: logging)

    async def clear(session_id):
        calls.append(("clear", session_id))

    monkeypatch.setattr(
        langgraph,
        "_load_sessions",
        lambda: SimpleNamespace(clear_session=clear),
    )
    discord = FakeDiscord()
    adapter = langgraph.LangGraphAgentAdapter(discord, 123)

    assert calls == []

    await adapter.clear("session-1")
    await adapter.startup()

    assert calls == [
        ("clear", "session-1"),
        ("configure", discord, 123),
        ("start_logs",),
        ("startup_notification",),
    ]


def test_dispatcher_starts_only_once(monkeypatch):
    calls = []

    class FakeLoop:
        def run_forever(self):
            calls.append("run_forever")

    class FakeThread:
        def __init__(self, *, target, daemon):
            calls.append(("thread", daemon))
            self.target = target

        def start(self):
            calls.append("thread_start")

    monkeypatch.setattr(runtime, "loop_agent", None)
    monkeypatch.setattr(runtime, "dispatcher_started", False)
    monkeypatch.setattr(runtime, "start_log_processor", lambda: calls.append("logs"))
    monkeypatch.setattr(runtime.asyncio, "new_event_loop", FakeLoop)
    monkeypatch.setattr(runtime.threading, "Thread", FakeThread)
    monkeypatch.setattr(
        runtime.asyncio,
        "run_coroutine_threadsafe",
        lambda coroutine, loop: calls.append(("scheduled", loop)) or coroutine.close(),
    )

    first = runtime.start_dispatcher("User", {"timestamp": 1})
    second = runtime.start_dispatcher("User", {"timestamp": 1})

    assert first is second
    assert calls.count("thread_start") == 1
    assert (
        len(
            [
                call
                for call in calls
                if isinstance(call, tuple) and call[0] == "scheduled"
            ]
        )
        == 1
    )
