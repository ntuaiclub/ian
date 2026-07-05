import ast
from pathlib import Path


def test_pytest_baseline_is_configured():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert '"pytest"' in pyproject
    assert "[tool.pytest.ini_options]" in pyproject
    assert 'pythonpath = ["src"]' in pyproject
    assert 'testpaths = ["tests"]' in pyproject


def test_expected_test_directories_exist():
    for directory in ["domain", "services", "agent", "integration"]:
        assert Path("tests", directory).is_dir()


def test_integration_placeholder_exists_and_is_module_skipped():
    placeholder = Path("tests/integration/test_integration_placeholder.py")

    assert placeholder.exists()

    tree = ast.parse(placeholder.read_text(encoding="utf-8"))
    skip_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "skip"
    ]

    assert any(
        any(
            keyword.arg == "allow_module_level"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in call.keywords
        )
        for call in skip_calls
    )


def test_contribution_docs_describe_test_baseline():
    contribution = Path("CONTRIBUTION.md").read_text(encoding="utf-8")
    architecture = Path("ARCHITECTURE.md").read_text(encoding="utf-8")

    assert "make test" in contribution
    assert "domain" in contribution
    assert "services" in contribution
    assert "agent" in contribution
    assert "integration" in contribution
    assert "integration" in architecture
