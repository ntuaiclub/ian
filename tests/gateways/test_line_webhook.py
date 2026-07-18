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
from types import SimpleNamespace

import pytest

from ian.gateways import line_webhook
from ian.gateways.agent_bridge import AgentMessageResult


def _event(text, *, group_id=None):
    source = SimpleNamespace(user_id="user-1")
    if group_id is not None:
        source.group_id = group_id
    return SimpleNamespace(
        message=SimpleNamespace(text=text),
        source=source,
        reply_token="reply-token",
    )


def test_handle_line_message_skips_non_whitelisted_group(monkeypatch, capsys):
    monkeypatch.setattr(line_webhook, "LINE_ALLOWED_GROUPS", ["allowed-group"])
    monkeypatch.setattr(
        line_webhook.line_bot_api,
        "reply_message",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("LINE API should not be called")
        ),
    )
    monkeypatch.setattr(
        line_webhook.requests,
        "post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("loading API should not be called")
        ),
    )
    monkeypatch.setattr(
        line_webhook.threading,
        "Thread",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("background task should not start")
        ),
    )

    assert line_webhook.handle_line_message(_event("hello", group_id="blocked")) is None
    entry = json.loads(capsys.readouterr().err)
    assert entry["event"] == "request_ignored"
    assert entry["status"] == "unauthorized"
    assert "blocked" not in json.dumps(entry)
    assert "user-1" not in json.dumps(entry)


@pytest.mark.parametrize("text", ["", "   "])
def test_handle_line_message_replies_to_empty_message(monkeypatch, text):
    replies = []
    monkeypatch.setattr(
        line_webhook.line_bot_api,
        "reply_message",
        lambda token, message: replies.append((token, message.text)),
    )
    monkeypatch.setattr(
        line_webhook.requests,
        "post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("loading API should not be called")
        ),
    )

    line_webhook.handle_line_message(_event(text))

    assert replies == [("reply-token", "請輸入您的問題！")]


def _stub_line_task(monkeypatch, agent_result):
    replies = []
    history = []

    async def fake_agent(**_kwargs):
        return agent_result

    async def find_member(*_args):
        return None

    monkeypatch.setattr(line_webhook, "get_line_user_profile", lambda _id: "Alice")
    monkeypatch.setattr(
        line_webhook.member_service, "find_user_by_platform", find_member
    )
    monkeypatch.setattr(line_webhook, "run_agent_message_flow", fake_agent)
    monkeypatch.setattr(
        line_webhook.line_bot_api,
        "reply_message",
        lambda token, messages: replies.append((token, messages)),
    )
    monkeypatch.setattr(
        line_webhook,
        "save_chat_history",
        lambda *args: history.append(args),
    )
    return replies, history


@pytest.mark.parametrize(
    "agent_result",
    [
        pytest.param(
            AgentMessageResult(text="[NO_RESPONSE]", should_reply=False),
            id="agent-no-response",
        ),
        pytest.param(
            AgentMessageResult(text="已達今日使用上限", should_reply=True),
            id="usage-limit",
        ),
    ],
)
def test_process_line_message_task_skips_no_reply_results(
    monkeypatch, capsys, agent_result
):
    replies, history = _stub_line_task(monkeypatch, agent_result)

    asyncio.run(
        line_webhook.process_line_message_task(
            "reply-token", "user-1", "hello", "chat-1", "1on1"
        )
    )

    assert replies == []
    assert history == []
    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [entry["event"] for entry in entries] == ["agent_invoked", "no_response"]
    assert "user-1" not in json.dumps(entries)
    assert "hello" not in json.dumps(entries)


def test_process_line_message_task_replies_with_message_chunks(monkeypatch, capsys):
    response = "x" * 2001
    replies, history = _stub_line_task(
        monkeypatch,
        AgentMessageResult(text=response, should_reply=True),
    )

    asyncio.run(
        line_webhook.process_line_message_task(
            "reply-token", "user-1", "hello", "chat-1", "1on1"
        )
    )

    assert len(replies) == 1
    token, messages = replies[0]
    assert token == "reply-token"
    assert [message.text for message in messages] == ["x" * 2000, "x"]
    assert history == [("user-1", "Alice", "hello", response, "LINE")]
    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [entry["event"] for entry in entries] == ["agent_invoked", "reply_sent"]
    assert entries[-1]["message_count"] == 2
    assert "user-1" not in json.dumps(entries)
    assert "hello" not in json.dumps(entries)


def test_process_line_message_task_logs_reply_failure_without_private_data(
    monkeypatch, capsys
):
    _replies, history = _stub_line_task(
        monkeypatch,
        AgentMessageResult(text="private agent reply", should_reply=True),
    )
    monkeypatch.setattr(
        line_webhook.line_bot_api,
        "reply_message",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("private LINE detail")),
    )

    asyncio.run(
        line_webhook.process_line_message_task(
            "reply-token", "user-1", "private question", "chat-1", "1on1"
        )
    )

    assert history == []
    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert entries[-1]["event"] == "external_send_failure"
    assert entries[-1]["error_type"] == "RuntimeError"
    for sensitive in (
        "reply-token",
        "user-1",
        "chat-1",
        "private question",
        "private agent reply",
        "private LINE detail",
    ):
        assert sensitive not in json.dumps(entries)
