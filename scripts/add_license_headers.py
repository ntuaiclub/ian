#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 NTU AI Club
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


LICENSE_ID = "GPL-3.0-or-later"
COPYRIGHT = "2026 NTU AI Club"

EXCLUDED = {
    "COPYING",
    "uv.lock",
    ".python-version",
}

SIDECAR_REQUIRED = {
    "assets/ian.jpg",
}

HASH_COMMENT_SUFFIXES = {
    ".py",
    ".toml",
    ".yaml",
    ".yml",
    ".example",
}

HASH_COMMENT_NAMES = {
    ".dockerignore",
    ".env.example",
    ".gitignore",
    ".pre-commit-config.yaml",
    "Dockerfile",
    "Makefile",
}

MARKDOWN_SUFFIXES = {".md"}


def tracked_files() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files"], text=True)
    return [Path(line) for line in output.splitlines() if line]


def header_for(path: Path) -> str | None:
    if path.as_posix() in SIDECAR_REQUIRED:
        return None
    if path.name in HASH_COMMENT_NAMES or path.suffix in HASH_COMMENT_SUFFIXES:
        return (
            f"# SPDX-FileCopyrightText: {COPYRIGHT}\n"
            f"# SPDX-License-Identifier: {LICENSE_ID}\n"
        )
    if path.suffix in MARKDOWN_SUFFIXES:
        return (
            f"<!-- SPDX-FileCopyrightText: {COPYRIGHT} -->\n"
            f"<!-- SPDX-License-Identifier: {LICENSE_ID} -->\n"
        )
    return None


def has_spdx(text: str) -> bool:
    return "SPDX-License-Identifier:" in text and "SPDX-FileCopyrightText:" in text


def insert_header(path: Path, header: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if has_spdx(text):
        return False

    if path.suffix == ".py" and text.startswith("#!"):
        first, rest = text.split("\n", 1)
        path.write_text(f"{first}\n{header}\n{rest}", encoding="utf-8")
        return True

    path.write_text(f"{header}\n{text}", encoding="utf-8")
    return True


def missing_files() -> list[str]:
    missing: list[str] = []
    for path in tracked_files():
        posix = path.as_posix()
        if posix in EXCLUDED:
            continue
        if posix in SIDECAR_REQUIRED:
            sidecar = Path(f"{posix}.license")
            if not sidecar.exists() or not has_spdx(
                sidecar.read_text(encoding="utf-8")
            ):
                missing.append(posix)
            continue

        header = header_for(path)
        if header is None:
            continue
        if not has_spdx(path.read_text(encoding="utf-8")):
            missing.append(posix)
    return missing


def add_headers() -> list[str]:
    changed: list[str] = []
    for path in tracked_files():
        posix = path.as_posix()
        if posix in EXCLUDED or posix in SIDECAR_REQUIRED:
            continue
        header = header_for(path)
        if header and insert_header(path, header):
            changed.append(posix)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.check:
        missing = missing_files()
        if missing:
            print("Missing SPDX license metadata:")
            for path in missing:
                print(f"- {path}")
            return 1
        return 0

    changed = add_headers()
    for path in changed:
        print(f"added SPDX header: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
