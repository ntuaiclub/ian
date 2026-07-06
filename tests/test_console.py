# SPDX-FileCopyrightText: 2026 NTU AI Club
# SPDX-License-Identifier: GPL-3.0-or-later

from ian.utils.console import eprint


def test_eprint_writes_to_stderr(capsys):
    eprint("hello", "stderr")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "hello stderr\n"
