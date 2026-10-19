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
from concurrent.futures import Future
from queue import Queue
from threading import Lock
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ian.infrastructure.agent import runtime


@pytest.mark.parametrize(
    "timestamp",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
    ],
)
def test_invalid_request_timestamp_does_not_stop_dispatcher(monkeypatch, timestamp):
    request_queue = Queue()
    invalid_future = Future()
    valid_future = Future()
    request_queue.put(
        (
            "invalid-session",
            "User",
            "invalid request",
            "member",
            timestamp,
            "channel",
            "test",
            "account",
            None,
            invalid_future,
        )
    )
    request_queue.put(
        (
            "valid-session",
            "User",
            "valid request",
            "member",
            1_700_000_000.0,
            "channel",
            "test",
            "account",
            None,
            valid_future,
        )
    )
    cancelled_future = Future()
    assert cancelled_future.cancel()
    request_queue.put(
        (
            "cancelled-session",
            "User",
            "cancelled request",
            "member",
            1_700_000_000.0,
            "channel",
            "test",
            "account",
            None,
            cancelled_future,
        )
    )
    request_queue.put((None, None, None, None, None, None, None, None, None, None))

    agent = Mock()
    agent.ainvoke = AsyncMock(
        return_value={"messages": [SimpleNamespace(type="ai", content="reply")]}
    )
    client = Mock()
    client.get_tools = AsyncMock(return_value=[])
    client.aclose = AsyncMock()
    llm = Mock()
    llm.with_fallbacks.return_value = llm
    session = {"agent": None, "channel_id": "channel"}
    reset_session_agent = Mock()

    monkeypatch.setattr(runtime, "request_queue", request_queue)
    monkeypatch.setattr(runtime, "MultiServerMCPClient", Mock(return_value=client))
    monkeypatch.setattr(runtime, "ChatGoogleGenerativeAI", Mock(return_value=llm))
    monkeypatch.setattr(runtime, "create_agent", Mock(return_value=agent))
    monkeypatch.setattr(runtime, "MemorySaver", Mock())
    monkeypatch.setattr(runtime, "sessions_lock", Lock())
    monkeypatch.setattr(runtime, "clear_session_if_timeout", Mock())
    monkeypatch.setattr(runtime, "upsert_session", Mock(return_value=(session, True)))
    monkeypatch.setattr(runtime, "set_session_agent", Mock())
    monkeypatch.setattr(
        runtime,
        "get_session_agent_and_channel",
        Mock(return_value=(agent, "channel")),
    )
    monkeypatch.setattr(runtime, "reset_session_agent", reset_session_agent)
    monkeypatch.setattr(runtime, "add_log", Mock())
    monkeypatch.setattr(runtime, "log_event", Mock())
    monkeypatch.setattr(
        runtime,
        "_validate_agent_response_urls",
        lambda response, _tool_results: response,
    )

    async def run_worker():
        worker = asyncio.create_task(runtime.run_agentic_workflow())
        await asyncio.wait_for(worker, timeout=5)

    asyncio.run(run_worker())

    assert invalid_future.done()
    assert "Error occurred, please try again later." in invalid_future.result()
    assert valid_future.done()
    assert valid_future.result(timeout=0) == "reply"
    assert cancelled_future.cancelled()
    reset_session_agent.assert_not_called()
    agent.ainvoke.assert_awaited_once()
    client.aclose.assert_awaited_once()
