from ian.services import notifications
from ian.services.agent import logging as agent_logging


class FakeResponse:
    def __init__(self, status_code=200, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_create_dm_channel_posts_recipient_with_bot_headers(monkeypatch):
    from ian.services import discord_api

    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse(200, payload={"id": "dm-1"})

    monkeypatch.setattr(discord_api, "DISCORD_BOT_TOKEN", "bot-token")
    monkeypatch.setattr(discord_api.requests, "post", fake_post)

    response = discord_api.create_dm_channel("user-1")

    assert response.json() == {"id": "dm-1"}
    assert calls == [
        {
            "url": "https://discord.com/api/v10/users/@me/channels",
            "headers": {
                "Authorization": "Bot bot-token",
                "Content-Type": "application/json",
            },
            "json": {"recipient_id": "user-1"},
            "timeout": 10,
        }
    ]


def test_send_channel_message_posts_content_with_bot_headers(monkeypatch):
    from ian.services import discord_api

    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse(201, payload={"id": "message-1"})

    monkeypatch.setattr(discord_api, "DISCORD_BOT_TOKEN", "bot-token")
    monkeypatch.setattr(discord_api.requests, "post", fake_post)

    response = discord_api.send_channel_message("channel-1", "hello")

    assert response.status_code == 201
    assert calls == [
        {
            "url": "https://discord.com/api/v10/channels/channel-1/messages",
            "headers": {
                "Authorization": "Bot bot-token",
                "Content-Type": "application/json",
            },
            "json": {"content": "hello"},
            "timeout": 10,
        }
    ]


def test_send_discord_dm_uses_shared_client_and_preserves_failure_message(
    monkeypatch, capsys
):
    from ian.services import discord_api

    def fake_create_dm_channel(user_id):
        assert user_id == "user-1"
        return FakeResponse(500, text="cannot create")

    monkeypatch.setattr(discord_api, "create_dm_channel", fake_create_dm_channel)

    assert notifications.send_discord_dm("user-1", "hello") is False

    captured = capsys.readouterr()
    assert "Failed to create DM channel for user-1: cannot create" in captured.err


def test_send_discord_channel_message_uses_shared_client_for_success(monkeypatch, capsys):
    from ian.services import discord_api

    calls = []

    def fake_send_channel_message(channel_id, message):
        calls.append((channel_id, message))
        return FakeResponse(201, text="created")

    monkeypatch.setattr(discord_api, "send_channel_message", fake_send_channel_message)

    assert notifications.send_discord_channel_message("channel-1", "hello") is True
    assert calls == [("channel-1", "hello")]

    captured = capsys.readouterr()
    assert "成功發送通知到 Discord channel channel-1" in captured.err


def test_agent_logging_uses_shared_client_for_failure(monkeypatch, capsys):
    from ian.services import discord_api

    calls = []

    def fake_send_channel_message(channel_id, message):
        calls.append((channel_id, message))
        return FakeResponse(500, text="boom")

    monkeypatch.setattr(agent_logging, "LOG_CHANNEL_ID", 123)
    monkeypatch.setattr(discord_api, "send_channel_message", fake_send_channel_message)

    agent_logging._send_log_to_discord_sync({"type": "INFO", "message": "hello"})

    assert calls == [(123, "```\n[] INFO\n└─ hello\n```")]
    captured = capsys.readouterr()
    assert "Failed to send log to Discord: 500 - boom" in captured.err
