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

import subprocess
import time
from collections.abc import Callable, Sequence
from urllib.error import URLError
from urllib.request import urlopen

from ian.utils.logging import elapsed_ms, log_event


Command = list[str]


def build_serve_commands(mcp_port: int = 5191) -> list[Command]:
    return [
        ["ian", "mcp", "--http", "--port", str(mcp_port)],
        ["ian", "webhook"],
        ["ian", "reminder", "--daemon"],
        ["ian", "discord"],
    ]


def wait_for_http_health(url: str, timeout_seconds: int = 90) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1):
                return
        except (OSError, URLError):
            time.sleep(1)

    raise TimeoutError(f"Service health check timed out: {url}")


def stop_processes(processes: Sequence[subprocess.Popen]) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()

    for process in reversed(processes):
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def serve_all(
    *,
    mcp_port: int = 5191,
    health_timeout: int = 90,
    popen_factory: Callable[[Command], subprocess.Popen] = subprocess.Popen,
    wait_for_http: Callable[[str, int], None] = wait_for_http_health,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    commands = build_serve_commands(mcp_port=mcp_port)
    processes: list[subprocess.Popen] = []
    started_at = time.monotonic()

    try:
        log_event(
            "job_started",
            "service_supervisor",
            status="started",
            job="serve_all",
        )
        processes.append(popen_factory(commands[0]))
        log_event(
            "service_started",
            "service_supervisor",
            status="starting",
            service="mcp",
        )

        log_event(
            "health_wait_started",
            "service_supervisor",
            status="waiting",
            service="mcp",
            timeout_seconds=health_timeout,
        )
        wait_for_http(f"http://localhost:{mcp_port}/health", health_timeout)
        log_event(
            "service_ready",
            "service_supervisor",
            status="ready",
            service="mcp",
        )

        for command in commands[1:]:
            processes.append(popen_factory(command))
            log_event(
                "service_started",
                "service_supervisor",
                status="starting",
                service=command[1],
            )

        while True:
            for index, process in enumerate(processes):
                returncode = process.poll()
                if returncode is not None:
                    log_event(
                        "job_failed",
                        "service_supervisor",
                        level="error",
                        status="unexpected_exit",
                        duration_ms=elapsed_ms(started_at),
                        job="serve_all",
                        service=commands[index][1],
                        return_code=returncode,
                    )
                    return returncode
            sleep(1)
    except KeyboardInterrupt:
        log_event(
            "job_completed",
            "service_supervisor",
            status="interrupted",
            duration_ms=elapsed_ms(started_at),
            job="serve_all",
        )
        return 130
    except Exception as e:
        log_event(
            "job_failed",
            "service_supervisor",
            level="error",
            status="error",
            duration_ms=elapsed_ms(started_at),
            job="serve_all",
            error=e,
        )
        raise
    finally:
        stop_processes(processes)
