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

import json
from types import SimpleNamespace

import pytest

from ian.services import notifications
from ian.application.members import ReminderRecipient
from ian.domain.members import MemberTier, Platform


@pytest.mark.parametrize(
    ("platform", "sender_name"),
    [
        (Platform.DISCORD, "send_discord_dm"),
        (Platform.FB, "send_facebook_message"),
        (Platform.LINE, "send_line_message"),
    ],
)
def test_send_notification_dispatches_by_platform(monkeypatch, platform, sender_name):
    calls = []
    target = ReminderRecipient(
        user_id=1,
        name="Member",
        email="member@example.test",
        platform=platform,
        account_id="account-1",
        tier=MemberTier.LECTURE_EXPLORATION,
    )
    monkeypatch.setattr(
        notifications,
        sender_name,
        lambda account_id, message: calls.append((account_id, message)) or True,
    )

    assert notifications.send_notification(target, "Notice") is True
    assert calls == [("account-1", "Notice")]


@pytest.mark.asyncio
async def test_platform_notification_sender_runs_sync_delivery_and_throttles(
    monkeypatch,
):
    recipient = ReminderRecipient(
        user_id=1,
        name="Member",
        email="member@example.test",
        platform=Platform.DISCORD,
        account_id="account-1",
        tier=MemberTier.LECTURE_EXPLORATION,
    )
    calls = []
    monkeypatch.setattr(
        notifications,
        "send_notification",
        lambda target, message: calls.append((target, message)) or True,
    )
    monkeypatch.setattr(notifications.time, "sleep", calls.append)

    sender = notifications.PlatformNotificationSender(delay_seconds=0.5)

    assert await sender.send(recipient, "Notice") is True
    assert calls == [(recipient, "Notice"), 0.5]


def test_rate_limit_retry_honors_retry_after(monkeypatch):
    responses = iter(
        [
            SimpleNamespace(status_code=429, headers={"Retry-After": "0.25"}),
            SimpleNamespace(status_code=200, headers={}),
        ]
    )
    sleeps = []
    monkeypatch.setattr(notifications.time, "sleep", sleeps.append)

    response = notifications._call_with_rate_limit_retry(lambda: next(responses))

    assert response.status_code == 200
    assert sleeps == [0.25]


def test_send_facebook_message_uses_page_api(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications, "PAGE_ACCESS_TOKEN", "page-token")
    monkeypatch.setattr(
        notifications.requests,
        "post",
        lambda url, **kwargs: (
            calls.append((url, kwargs)) or SimpleNamespace(status_code=200)
        ),
    )

    assert notifications.send_facebook_message("fb-1", "Notice") is True
    assert calls[0][0].endswith("/me/messages")
    assert calls[0][1]["params"] == {"access_token": "page-token"}
    assert calls[0][1]["json"] == {
        "recipient": {"id": "fb-1"},
        "message": {"text": "Notice"},
    }


def test_send_line_message_uses_push_api(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications, "LINE_CHANNEL_ACCESS_TOKEN", "line-token")
    monkeypatch.setattr(
        notifications.requests,
        "post",
        lambda url, **kwargs: (
            calls.append((url, kwargs)) or SimpleNamespace(status_code=200)
        ),
    )

    assert notifications.send_line_message("line-1", "Notice") is True
    assert calls[0][0].endswith("/v2/bot/message/push")
    assert calls[0][1]["headers"]["Authorization"] == "Bearer line-token"
    assert calls[0][1]["json"] == {
        "to": "line-1",
        "messages": [{"type": "text", "text": "Notice"}],
    }


@pytest.mark.parametrize(
    ("create_status", "send_status", "expected", "expected_stage"),
    [
        pytest.param(500, None, False, "create_channel", id="create-channel-failure"),
        pytest.param(200, 500, False, "send_message", id="send-message-failure"),
        pytest.param(200, 200, True, "send_message", id="success"),
    ],
)
def test_send_discord_dm_emits_redacted_delivery_result(
    monkeypatch,
    capsys,
    create_status,
    send_status,
    expected,
    expected_stage,
):
    send_calls = []
    monkeypatch.setattr(
        notifications.discord_api,
        "create_dm_channel",
        lambda _user_id: SimpleNamespace(
            status_code=create_status,
            text="private create response",
            json=lambda: {"id": "dm-channel-1"},
        ),
    )
    monkeypatch.setattr(
        notifications.discord_api,
        "send_channel_message",
        lambda channel_id, message: (
            send_calls.append((channel_id, message))
            or SimpleNamespace(status_code=send_status, text="private send response")
        ),
    )

    result = notifications.send_discord_dm("user-1", "private message")

    assert result is expected
    assert send_calls == (
        [] if send_status is None else [("dm-channel-1", "private message")]
    )
    log_entry = json.loads(capsys.readouterr().err)
    assert log_entry["status"] == ("success" if expected else "failure")
    assert log_entry["stage"] == expected_stage
    serialized = json.dumps(log_entry)
    for sensitive in (
        "user-1",
        "dm-channel-1",
        "private message",
        "private create response",
        "private send response",
    ):
        assert sensitive not in serialized


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        pytest.param(200, True, id="ok"),
        pytest.param(201, True, id="created"),
        pytest.param(400, False, id="bad-request"),
        pytest.param(500, False, id="server-error"),
    ],
)
def test_send_discord_channel_message_handles_response_statuses(
    monkeypatch, capsys, status_code, expected
):
    calls = []
    monkeypatch.setattr(
        notifications.discord_api,
        "send_channel_message",
        lambda channel_id, message: (
            calls.append((channel_id, message))
            or SimpleNamespace(status_code=status_code, text="response body")
        ),
    )

    assert notifications.send_discord_channel_message("channel-1", "Notice") is expected
    assert calls == [("channel-1", "Notice")]
    log_entry = json.loads(capsys.readouterr().err)
    assert log_entry["status"] == ("success" if expected else "failure")
    assert log_entry["http_status"] == status_code
    assert "channel-1" not in json.dumps(log_entry)
    assert "response body" not in json.dumps(log_entry)


def test_send_discord_channel_message_handles_api_exception(monkeypatch, capsys):
    def fail(*_args):
        raise RuntimeError("Discord unavailable")

    monkeypatch.setattr(notifications.discord_api, "send_channel_message", fail)

    assert notifications.send_discord_channel_message("channel-1", "Notice") is False
    log_entry = json.loads(capsys.readouterr().err)
    assert log_entry["level"] == "error"
    assert log_entry["status"] == "error"
    assert log_entry["error_type"] == "RuntimeError"
    assert "Discord unavailable" not in json.dumps(log_entry)


@pytest.mark.parametrize(
    ("token", "channel_id"),
    [
        pytest.param("", "channel-1", id="missing-token"),
        pytest.param("token", "", id="missing-channel"),
        pytest.param("", "", id="missing-token-and-channel"),
    ],
)
def test_send_log_is_noop_when_not_configured(monkeypatch, token, channel_id):
    monkeypatch.setattr(notifications, "DISCORD_BOT_TOKEN", token)
    monkeypatch.setattr(notifications, "LOG_CHANNEL_ID", channel_id)
    monkeypatch.setattr(
        notifications,
        "send_discord_channel_message",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("Discord should not be called")
        ),
    )

    assert notifications.send_log("log message") is None


def test_send_log_delegates_when_configured(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications, "DISCORD_BOT_TOKEN", "token")
    monkeypatch.setattr(notifications, "LOG_CHANNEL_ID", "log-channel")
    monkeypatch.setattr(
        notifications,
        "send_discord_channel_message",
        lambda channel_id, message: calls.append((channel_id, message)) or True,
    )

    notifications.send_log("log message")

    assert calls == [("log-channel", "log message")]
