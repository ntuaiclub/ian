import ast
from pathlib import Path


GATEWAY_ENTRYPOINTS = [
    Path("src/ian/gateways/discord_bot.py"),
    Path("src/ian/gateways/mcp_server.py"),
    Path("src/ian/gateways/webhook_server.py"),
]


def test_gateway_modules_expose_entrypoints_for_cli_delegation():
    for gateway_file in GATEWAY_ENTRYPOINTS:
        tree = ast.parse(gateway_file.read_text(encoding="utf-8"))
        function_names = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }

        assert "entrypoint" in function_names
        assert "main" not in function_names


def test_gateway_modules_do_not_run_as_direct_scripts():
    for gateway_file in GATEWAY_ENTRYPOINTS:
        source = gateway_file.read_text(encoding="utf-8")

        assert '__name__ == "__main__"' not in source
        assert "__name__ == '__main__'" not in source


def test_docker_uses_cli_serve_entrypoint():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert 'CMD ["ian", "serve"]' in dockerfile
    assert "start.sh" not in dockerfile
    assert not Path("start.sh").exists()
