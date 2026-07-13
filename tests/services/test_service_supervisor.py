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

import json

import pytest

from ian.services.service_supervisor import build_serve_commands, serve_all


class FakeProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True


def test_build_serve_commands_uses_cli_subcommands_in_startup_order():
    commands = build_serve_commands(mcp_port=6001)

    assert commands == [
        ["ian", "mcp", "--http", "--port", "6001"],
        ["ian", "webhook"],
        ["ian", "reminder", "--daemon"],
        ["ian", "discord"],
    ]


def test_serve_all_waits_for_mcp_before_starting_other_services(capsys):
    started = []
    health_checks = []
    processes = [FakeProcess(), FakeProcess(), FakeProcess(), FakeProcess(returncode=0)]

    def fake_popen(command):
        started.append(command)
        return processes[len(started) - 1]

    def fake_wait_for_http(url, timeout_seconds):
        health_checks.append({"url": url, "timeout_seconds": timeout_seconds, "started": list(started)})

    def fake_sleep(seconds):
        return None

    exit_code = serve_all(
        mcp_port=6001,
        health_timeout=10,
        popen_factory=fake_popen,
        wait_for_http=fake_wait_for_http,
        sleep=fake_sleep,
    )

    assert exit_code == 0
    assert health_checks == [
        {
            "url": "http://localhost:6001/health",
            "timeout_seconds": 10,
            "started": [["ian", "mcp", "--http", "--port", "6001"]],
        }
    ]
    assert started == [
        ["ian", "mcp", "--http", "--port", "6001"],
        ["ian", "webhook"],
        ["ian", "reminder", "--daemon"],
        ["ian", "discord"],
    ]
    assert [process.terminated for process in processes] == [True, True, True, False]
    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [entry["event"] for entry in entries] == [
        "job_started",
        "service_started",
        "health_wait_started",
        "service_ready",
        "service_started",
        "service_started",
        "service_started",
        "job_failed",
    ]
    assert [entry["service"] for entry in entries if "service" in entry] == [
        "mcp",
        "mcp",
        "mcp",
        "webhook",
        "reminder",
        "discord",
        "discord",
    ]
    assert entries[-1]["status"] == "unexpected_exit"


def test_serve_all_logs_health_failure_and_stops_started_process(capsys):
    process = FakeProcess()

    def fail_health(_url, _timeout):
        raise TimeoutError("private health URL")

    with pytest.raises(TimeoutError, match="private health URL"):
        serve_all(
            popen_factory=lambda _command: process,
            wait_for_http=fail_health,
        )

    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert entries[-1]["event"] == "job_failed"
    assert entries[-1]["error_type"] == "TimeoutError"
    assert "private health URL" not in json.dumps(entries)
    assert process.terminated is True
