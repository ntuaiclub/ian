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

from ian.gateways import facebook_webhook
from ian.gateways.agent_bridge import AgentMessageResult


def test_cleanup_processed_messages_removes_only_expired_entries(monkeypatch):
    monkeypatch.setattr(
        facebook_webhook,
        "PROCESSED_MESSAGES",
        {"expired": 399.0, "boundary": 400.0, "recent": 999.0},
    )
    monkeypatch.setattr(facebook_webhook.time, "time", lambda: 1000.0)

    facebook_webhook.cleanup_processed_messages()

    assert facebook_webhook.PROCESSED_MESSAGES == {
        "boundary": 400.0,
        "recent": 999.0,
    }


@pytest.mark.parametrize(
    ("message", "processed_messages"),
    [
        pytest.param(
            {"mid": "duplicate", "text": "hello"},
            {"duplicate": 1.0},
            id="duplicate-mid",
        ),
        pytest.param(
            {"mid": "echo", "text": "hello", "is_echo": True},
            {},
            id="echo",
        ),
        pytest.param({"text": "hello"}, {}, id="missing-mid"),
    ],
)
def test_handle_facebook_messages_skips_nonprocessable_messages(
    monkeypatch, message, processed_messages
):
    expected_processed_messages = processed_messages.copy()
    monkeypatch.setattr(facebook_webhook, "PROCESSED_MESSAGES", processed_messages)
    monkeypatch.setattr(facebook_webhook, "cleanup_processed_messages", lambda: None)
    monkeypatch.setattr(
        facebook_webhook,
        "process_message_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("message should not be processed")
        ),
    )

    facebook_webhook.handle_facebook_messages(
        {"entry": [{"messaging": [{"sender": {"id": "sender-1"}, "message": message}]}]}
    )

    assert facebook_webhook.PROCESSED_MESSAGES == expected_processed_messages


def test_handle_facebook_messages_routes_new_message_to_background_task(
    monkeypatch, capsys
):
    processed = []

    async def fake_process(sender_id, text, mid):
        processed.append((sender_id, text, mid))

    class ImmediateThread:
        def __init__(self, target, args):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(facebook_webhook, "PROCESSED_MESSAGES", {})
    monkeypatch.setattr(facebook_webhook, "cleanup_processed_messages", lambda: None)
    monkeypatch.setattr(facebook_webhook.time, "time", lambda: 123.0)
    monkeypatch.setattr(facebook_webhook, "process_message_task", fake_process)
    monkeypatch.setattr(facebook_webhook.threading, "Thread", ImmediateThread)

    facebook_webhook.handle_facebook_messages(
        {
            "entry": [
                {
                    "messaging": [
                        {
                            "sender": {"id": "sender-1"},
                            "message": {"mid": "mid-1", "text": "hello"},
                        }
                    ]
                }
            ]
        }
    )

    assert facebook_webhook.PROCESSED_MESSAGES == {"mid-1": 123.0}
    assert processed == [("sender-1", "hello", "mid-1")]
    entry = json.loads(capsys.readouterr().err)
    assert entry["event"] == "request_received"
    assert entry["correlation_id"].startswith("sha256:")
    assert "sender-1" not in json.dumps(entry)
    assert "mid-1" not in json.dumps(entry)
    assert "hello" not in json.dumps(entry)


@pytest.mark.parametrize(
    ("mid", "reaction_emoji", "expected_reactions"),
    [
        pytest.param("mid-1", "🙏", [("sender-1", "mid-1", "🙏")], id="reaction"),
        pytest.param("mid-1", None, [], id="no-reaction"),
        pytest.param(None, "🙏", [], id="missing-mid"),
    ],
)
def test_process_message_task_handles_no_response_reactions(
    monkeypatch, capsys, mid, reaction_emoji, expected_reactions
):
    typing_calls = []
    reactions = []

    async def fake_typing(recipient_id, action, _correlation_id=None):
        typing_calls.append((recipient_id, action))

    async def fake_agent(**_kwargs):
        return AgentMessageResult(
            text="[NO_RESPONSE]",
            should_reply=False,
            reaction_emoji=reaction_emoji,
        )

    async def find_member(*_args):
        return None

    monkeypatch.setattr(facebook_webhook, "send_typing_indicator", fake_typing)
    monkeypatch.setattr(facebook_webhook, "get_fb_user_profile", lambda _id: "Alice")
    monkeypatch.setattr(
        facebook_webhook.member_service, "find_user_by_platform", find_member
    )
    monkeypatch.setattr(facebook_webhook, "run_agent_message_flow", fake_agent)
    monkeypatch.setattr(
        facebook_webhook,
        "send_reaction",
        lambda sender_id, message_id, emoji, _correlation_id=None: reactions.append(
            (sender_id, message_id, emoji)
        ),
    )
    monkeypatch.setattr(
        facebook_webhook,
        "send_message",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("Facebook message should not be sent")
        ),
    )
    monkeypatch.setattr(
        facebook_webhook,
        "save_chat_history",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("no-response should not be persisted")
        ),
    )

    asyncio.run(facebook_webhook.process_message_task("sender-1", "hello", mid=mid))

    assert typing_calls == [
        ("sender-1", "typing_on"),
        ("sender-1", "typing_off"),
    ]
    assert reactions == expected_reactions
    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [entry["event"] for entry in entries] == ["agent_invoked", "no_response"]
    assert "sender-1" not in json.dumps(entries)
    assert "hello" not in json.dumps(entries)


@pytest.mark.parametrize(
    ("status_code", "expected_event", "expected_status"),
    [
        pytest.param(200, "reply_sent", "success", id="success"),
        pytest.param(500, "external_send_failure", "failure", id="http-failure"),
    ],
)
def test_send_message_emits_correlated_redacted_result(
    monkeypatch, capsys, status_code, expected_event, expected_status
):
    monkeypatch.setattr(
        facebook_webhook.requests,
        "post",
        lambda *_args, **_kwargs: SimpleNamespace(
            status_code=status_code,
            text="private response body",
        ),
    )

    facebook_webhook.send_message(
        "sender-1", "private reply", correlation_id="sha256:correlation"
    )

    entry = json.loads(capsys.readouterr().err)
    assert entry["event"] == expected_event
    assert entry["status"] == expected_status
    assert entry["correlation_id"] == "sha256:correlation"
    assert "sender-1" not in json.dumps(entry)
    assert "private reply" not in json.dumps(entry)
    assert "private response body" not in json.dumps(entry)
