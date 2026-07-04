import importlib.util
import os
import shutil


def test_config_loads_project_dotenv_before_reading_environment(monkeypatch, tmp_path):
    source = os.path.join(os.path.dirname(__file__), "..", "src", "ian", "config.py")
    project = tmp_path
    package_dir = project / "src" / "ian"
    package_dir.mkdir(parents=True)
    config_file = package_dir / "config.py"
    shutil.copyfile(source, config_file)

    dotenv_file = project / ".env"
    dotenv_file.write_text(
        "\n".join(
            [
                "DISCORD_BOT_TOKEN=token-from-dotenv",
                "MCP_PORT=6001",
                "DISCORD_ALLOWED_CHANNELS=123, 456",
            ]
        ),
        encoding="utf-8",
    )

    for key in ["DISCORD_BOT_TOKEN", "MCP_PORT", "DISCORD_ALLOWED_CHANNELS"]:
        monkeypatch.delenv(key, raising=False)

    spec = importlib.util.spec_from_file_location("isolated_ian_config", config_file)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.PROJECT_ROOT == project
    assert module.DISCORD_BOT_TOKEN == "token-from-dotenv"
    assert module.MCP_PORT == 6001
    assert module.ALLOWED_DISCORD_CHANNELS == ["123", "456"]
