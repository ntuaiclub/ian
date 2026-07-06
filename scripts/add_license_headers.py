#!/usr/bin/env python3
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

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


HASH_HEADER = """#
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
"""

MARKDOWN_HEADER = """<!--
SPDX-License-Identifier: GPL-3.0-or-later

Copyright (c) 2026 NTU AI Club

This file is part of Ian, an open-source AI agent framework developed
and maintained by NTU AI Club.

Ian is licensed under the GNU General Public License, either version 3
of the License, or (at your option) any later version.

Ian is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Ian. If not, see <https://www.gnu.org/licenses/>.
-->
"""

SIDECAR_HEADER = """SPDX-License-Identifier: GPL-3.0-or-later

Copyright (c) 2026 NTU AI Club

This file is part of Ian, an open-source AI agent framework developed
and maintained by NTU AI Club.

Ian is licensed under the GNU General Public License, either version 3
of the License, or (at your option) any later version.

Ian is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Ian. If not, see <https://www.gnu.org/licenses/>.
"""

OLD_HASH_HEADER = (
    "# SPDX-FileCopyrightText: 2026 NTU AI Club\n"
    "# SPDX-License-Identifier: GPL-3.0-or-later\n"
)

OLD_MARKDOWN_HEADER = (
    "<!-- SPDX-FileCopyrightText: 2026 NTU AI Club -->\n"
    "<!-- SPDX-License-Identifier: GPL-3.0-or-later -->\n"
)

EXCLUDED = {
    "uv.lock",
}

HEADER_COMMENT_SUFFIXES = {
    ".py",
}

HEADER_COMMENT_NAMES = {
    "Dockerfile",
    "Makefile",
}

CLEANUP_SUFFIXES = {
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".example",
}

CLEANUP_NAMES = {
    ".dockerignore",
    ".env.example",
    ".gitignore",
    ".pre-commit-config.yaml",
    ".python-version",
}


def tracked_files() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files"], text=True)
    return [Path(line) for line in output.splitlines() if line]


def header_for(path: Path) -> str | None:
    if path.name in HEADER_COMMENT_NAMES or path.suffix in HEADER_COMMENT_SUFFIXES:
        return HASH_HEADER
    return None


def has_license_metadata(text: str) -> bool:
    return (
        "SPDX-License-Identifier: GPL-3.0-or-later" in text
        and "Copyright (c) 2026 NTU AI Club" in text
    )


def strip_known_header(text: str) -> str:
    for prefix in (HASH_HEADER, MARKDOWN_HEADER, OLD_HASH_HEADER, OLD_MARKDOWN_HEADER):
        if text.startswith(prefix):
            return text[len(prefix) :].lstrip("\n")
    return text


def has_required_header(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py" and text.startswith("#!"):
        _, rest = text.split("\n", 1)
        return rest.startswith(HASH_HEADER)
    header = header_for(path)
    return bool(header and text.startswith(header))


def insert_header(path: Path, header: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py" and text.startswith("#!"):
        first, rest = text.split("\n", 1)
        stripped = strip_known_header(rest)
        updated = f"{first}\n{header}\n{stripped}"
        if updated == text:
            return False
        path.write_text(updated, encoding="utf-8")
        return True

    stripped = strip_known_header(text)
    updated = f"{header}\n{stripped}"
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def cleanup_header(path: Path) -> bool:
    if path.name not in CLEANUP_NAMES and path.suffix not in CLEANUP_SUFFIXES:
        return False

    text = path.read_text(encoding="utf-8")
    stripped = strip_known_header(text)
    if stripped == text:
        return False

    path.write_text(stripped, encoding="utf-8")
    return True


def missing_files() -> list[str]:
    missing: list[str] = []
    for path in tracked_files():
        posix = path.as_posix()
        if posix in EXCLUDED:
            continue

        header = header_for(path)
        if header is None:
            continue
        if not has_required_header(path):
            missing.append(posix)
    return missing


def add_headers() -> list[str]:
    changed: list[str] = []
    for path in tracked_files():
        posix = path.as_posix()
        if posix in EXCLUDED:
            continue
        header = header_for(path)
        if header and insert_header(path, header):
            changed.append(posix)
        elif header is None and cleanup_header(path):
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
        print(f"normalized license header: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
