# SPDX-FileCopyrightText: 2026 NTU AI Club
# SPDX-License-Identifier: GPL-3.0-or-later

import subprocess


def test_tracked_files_have_license_metadata():
    result = subprocess.run(
        ["uv", "run", "python", "scripts/add_license_headers.py", "--check"],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
