from pathlib import Path


def test_agent_package_exports_gateway_runtime_api():
    from ian.services import agent

    assert callable(agent.chat_with_agent)
    assert callable(agent.start_dispatcher)
    assert callable(agent.clear_session)
    assert callable(agent.parse_no_response)
    assert callable(agent.add_log)
    assert callable(agent.start_log_processor)
    assert callable(agent.send_startup_notification)


def test_gateways_import_agent_package_directly():
    gateway_files = [
        Path("src/ian/gateways/discord_bot.py"),
        Path("src/ian/gateways/facebook_webhook.py"),
        Path("src/ian/gateways/line_webhook.py"),
    ]

    for gateway_file in gateway_files:
        source = gateway_file.read_text()
        assert "ian.services.agent_runtime" not in source


def test_agent_runtime_has_prompt_and_session_modules():
    agent_dir = Path("src/ian/services/agent")
    runtime_source = (agent_dir / "runtime.py").read_text()

    assert (agent_dir / "prompt.py").exists()
    assert (agent_dir / "sessions.py").exists()
    assert "SYS_PROMPT =" not in runtime_source
    assert "sessions =" not in runtime_source
    assert "from ian.services.agent.prompt import SYS_PROMPT" in runtime_source
    assert "from ian.services.agent.sessions import" in runtime_source


def test_agent_runtime_uses_langchain_agent_factory():
    runtime_source = Path("src/ian/services/agent/runtime.py").read_text()

    assert "from langgraph.prebuilt" not in runtime_source
    assert "create_react_agent" not in runtime_source
    assert "from langchain.agents import create_agent" in runtime_source
