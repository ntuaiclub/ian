from pathlib import Path

import pytest

from ian.gateways import agent_bridge


@pytest.mark.anyio
async def test_agent_bridge_runs_agent_flow_for_normal_response():
    calls = []

    def fake_start_dispatcher(user_name, current_time):
        calls.append(("start", user_name, current_time))

    async def fake_chat_with_agent(
        session_id,
        user_name,
        user_message,
        roles,
        timestamp,
        channel_id,
        *,
        platform,
        account_id,
    ):
        calls.append(
            (
                "chat",
                session_id,
                user_name,
                user_message,
                roles,
                timestamp,
                channel_id,
                platform,
                account_id,
            )
        )
        return "正常回覆"

    result = await agent_bridge.run_agent_message_flow(
        session_id="session-1",
        user_name="Ian User",
        user_message="社課時間？",
        roles=["社員"],
        channel_id="channel-1",
        platform="Discord",
        account_id="account-1",
        current_time={"timestamp": 123.0},
        start_dispatcher_fn=fake_start_dispatcher,
        chat_with_agent_fn=fake_chat_with_agent,
    )

    assert result.should_reply is True
    assert result.text == "正常回覆"
    assert result.reaction_emoji is None
    assert calls == [
        ("start", "Ian User", {"timestamp": 123.0}),
        (
            "chat",
            "session-1",
            "Ian User",
            "社課時間？",
            ["社員"],
            123.0,
            "channel-1",
            "Discord",
            "account-1",
        ),
    ]


@pytest.mark.anyio
async def test_agent_bridge_parses_no_response_with_reaction():
    async def fake_chat_with_agent(*args, **kwargs):
        return "[NO_RESPONSE:🙏]"

    result = await agent_bridge.run_agent_message_flow(
        session_id="session-1",
        user_name="Ian User",
        user_message="謝謝",
        roles="社員",
        channel_id="channel-1",
        platform="FB",
        account_id="account-1",
        current_time={"timestamp": 456.0},
        start_dispatcher_fn=lambda *args: None,
        chat_with_agent_fn=fake_chat_with_agent,
    )

    assert result.should_reply is False
    assert result.text == "[NO_RESPONSE:🙏]"
    assert result.reaction_emoji == "🙏"


def test_gateways_delegate_core_agent_invocation_to_bridge():
    gateway_paths = [
        "src/ian/gateways/discord_bot.py",
        "src/ian/gateways/facebook_webhook.py",
        "src/ian/gateways/line_webhook.py",
    ]

    for path in gateway_paths:
        source = Path(path).read_text()
        assert "run_agent_message_flow" in source
        assert "chat_with_agent(" not in source
        assert "parse_no_response(" not in source
