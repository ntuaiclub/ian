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

from ian.application.members import ReminderRecipient
from ian.domain.members import MemberTier, Platform
from ian.infrastructure.notifications import adapters


class FakeDiscord:
    def create_dm_channel(self, _user_id):
        return SimpleNamespace(status_code=200, json=lambda: {"id": "dm-1"})

    def send_channel_message(self, _channel_id, _message):
        return SimpleNamespace(status_code=200, headers={})


def make_sender(**overrides):
    values = {
        "discord": FakeDiscord(),
        "page_access_token": "page-token",
        "line_channel_access_token": "line-token",
        "delay_seconds": 0,
    }
    values.update(overrides)
    return adapters.PlatformNotificationSender(**values)


def recipient(platform=Platform.DISCORD):
    return ReminderRecipient(
        user_id=1,
        name="Member",
        email="member@example.test",
        platform=platform,
        account_id="account-1",
        tier=MemberTier.LECTURE_EXPLORATION,
    )


@pytest.mark.parametrize(
    ("platform", "method_name"),
    [
        (Platform.DISCORD, "send_discord_dm"),
        (Platform.FB, "send_facebook_message"),
        (Platform.LINE, "send_line_message"),
    ],
)
def test_sender_dispatches_by_platform(monkeypatch, platform, method_name):
    sender = make_sender()
    calls = []
    monkeypatch.setattr(
        sender,
        method_name,
        lambda account_id, message: calls.append((account_id, message)) or True,
    )

    assert sender._dispatch(recipient(platform), "Notice") is True
    assert calls == [("account-1", "Notice")]


@pytest.mark.asyncio
async def test_sender_runs_sync_delivery_and_throttles(monkeypatch):
    sender = make_sender(delay_seconds=0.5)
    calls = []
    target = recipient()
    monkeypatch.setattr(
        sender,
        "_dispatch",
        lambda item, message: calls.append((item, message)) or True,
    )
    monkeypatch.setattr(adapters.time, "sleep", calls.append)

    assert await sender.send(target, "Notice") is True
    assert calls == [(target, "Notice"), 0.5]


def test_rate_limit_retry_honors_retry_after(monkeypatch):
    responses = iter(
        [
            SimpleNamespace(status_code=429, headers={"Retry-After": "0.25"}),
            SimpleNamespace(status_code=200, headers={}),
        ]
    )
    sleeps = []
    monkeypatch.setattr(adapters.time, "sleep", sleeps.append)

    response = adapters.call_with_rate_limit_retry(lambda: next(responses))

    assert response.status_code == 200
    assert sleeps == [0.25]


def test_facebook_sender_uses_page_api(monkeypatch):
    calls = []
    sender = make_sender()
    monkeypatch.setattr(
        adapters.requests,
        "post",
        lambda url, **kwargs: (
            calls.append((url, kwargs))
            or SimpleNamespace(status_code=200, headers={})
        ),
    )

    assert sender.send_facebook_message("fb-1", "Notice") is True
    assert calls[0][0].endswith("/me/messages")
    assert calls[0][1]["params"] == {"access_token": "page-token"}
    assert calls[0][1]["json"] == {
        "recipient": {"id": "fb-1"},
        "message": {"text": "Notice"},
    }


def test_line_sender_uses_push_api(monkeypatch):
    calls = []
    sender = make_sender()
    monkeypatch.setattr(
        adapters.requests,
        "post",
        lambda url, **kwargs: (
            calls.append((url, kwargs))
            or SimpleNamespace(status_code=200, headers={})
        ),
    )

    assert sender.send_line_message("line-1", "Notice") is True
    assert calls[0][0].endswith("/v2/bot/message/push")
    assert calls[0][1]["headers"]["Authorization"] == "Bearer line-token"


@pytest.mark.parametrize(
    ("create_status", "send_status", "expected", "stage"),
    [
        (500, None, False, "create_channel"),
        (200, 500, False, "send_message"),
        (200, 200, True, "send_message"),
    ],
)
def test_discord_dm_emits_redacted_result(
    monkeypatch, capsys, create_status, send_status, expected, stage
):
    discord = FakeDiscord()
    monkeypatch.setattr(
        discord,
        "create_dm_channel",
        lambda _user_id: SimpleNamespace(
            status_code=create_status,
            headers={},
            json=lambda: {"id": "dm-channel-1"},
        ),
    )
    monkeypatch.setattr(
        discord,
        "send_channel_message",
        lambda _channel, _message: SimpleNamespace(
            status_code=send_status,
            headers={},
        ),
    )
    sender = make_sender(discord=discord)

    assert sender.send_discord_dm("user-1", "private message") is expected

    entry = json.loads(capsys.readouterr().err)
    assert entry["stage"] == stage
    assert entry["status"] == ("success" if expected else "failure")
    assert "user-1" not in json.dumps(entry)
    assert "dm-channel-1" not in json.dumps(entry)
    assert "private message" not in json.dumps(entry)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(200, True), (201, True), (400, False), (500, False)],
)
async def test_operational_notifier_handles_channel_status(
    monkeypatch, capsys, status_code, expected
):
    discord = FakeDiscord()
    calls = []
    monkeypatch.setattr(
        discord,
        "send_channel_message",
        lambda channel, message: (
            calls.append((channel, message))
            or SimpleNamespace(status_code=status_code, headers={})
        ),
    )
    notifier = adapters.DiscordOperationalNotifier(
        discord,
        bot_token="token",
        log_channel_id="log-channel",
    )

    assert await notifier.send_channel("channel-1", "Notice") is expected
    assert calls == [("channel-1", "Notice")]
    entry = json.loads(capsys.readouterr().err)
    assert entry["status"] == ("success" if expected else "failure")
    assert "channel-1" not in json.dumps(entry)


@pytest.mark.asyncio
async def test_operational_log_is_noop_without_configuration(monkeypatch):
    discord = FakeDiscord()
    monkeypatch.setattr(
        discord,
        "send_channel_message",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not send")),
    )
    notifier = adapters.DiscordOperationalNotifier(
        discord,
        bot_token="",
        log_channel_id="",
    )

    assert await notifier.send_log("Notice") is None


@pytest.mark.asyncio
async def test_operational_log_uses_configured_channel(monkeypatch):
    discord = FakeDiscord()
    calls = []
    monkeypatch.setattr(
        discord,
        "send_channel_message",
        lambda channel, message: (
            calls.append((channel, message))
            or SimpleNamespace(status_code=200, headers={})
        ),
    )
    notifier = adapters.DiscordOperationalNotifier(
        discord,
        bot_token="token",
        log_channel_id="log-channel",
    )

    await notifier.send_log("Notice")

    assert calls == [("log-channel", "Notice")]
