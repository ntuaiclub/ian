import ast
from pathlib import Path


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
