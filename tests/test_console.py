import ast
from pathlib import Path

from ian.utils.console import eprint


def test_eprint_writes_to_stderr(capsys):
    eprint("hello", "stderr")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "hello stderr\n"


def test_modules_use_shared_eprint_helper():
    source_root = Path("src/ian")
    local_eprint_defs = []

    for source_file in source_root.rglob("*.py"):
        if source_file == source_root / "utils" / "console.py":
            continue

        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.FunctionDef) and node.name == "eprint"
            for node in ast.walk(tree)
        ):
            local_eprint_defs.append(str(source_file))

    assert local_eprint_defs == []
