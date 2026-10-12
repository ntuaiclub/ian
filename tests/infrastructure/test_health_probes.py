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

import asyncio
from unittest.mock import Mock

import pytest

from ian.infrastructure.health import (
    PayloadMcpReadinessProbe,
    PlatformConfiguration,
    PlatformReadinessProbe,
    RagReadinessProbe,
)
from ian.infrastructure.payload_mcp.client import (
    PayloadMcpConfigurationError,
    PayloadMcpTransportError,
)


def _check(probe):
    return asyncio.run(probe.check())


class StubCaller:
    def __init__(self, tools=None, error=None):
        self.tools = tools or set()
        self.error = error

    async def list_tools(self):
        if self.error is not None:
            raise self.error
        return self.tools


class StubRag:
    def __init__(self, initialized):
        self.initialized = initialized

    def is_initialized(self):
        return self.initialized


def test_payload_mcp_probe_reports_member_and_course_capabilities():
    metrics = Mock()
    checks = _check(
        PayloadMcpReadinessProbe(
            StubCaller(
                {"findUsers", "findMemberships", "updateUsers", "findEvents"}
            ),
            metrics=metrics,
        )
    )

    assert [check.name for check in checks] == ["member_data", "course_data"]
    assert all(check.ready for check in checks)
    assert metrics.record_dependency_check.call_count == 1
    assert metrics.record_dependency_check.call_args.args[:2] == (
        "payload_mcp",
        "ready",
    )


def test_payload_mcp_probe_reports_missing_tools_without_tool_names():
    member, course = _check(PayloadMcpReadinessProbe(StubCaller({"findUsers"})))

    assert member.as_dict() == {
        "status": "not_ready",
        "required": True,
        "source": "payload_mcp",
        "missing_tool_count": 2,
        "reason": "missing_tools",
    }
    assert course.ready is False


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (PayloadMcpConfigurationError("private key"), "missing_configuration"),
        (PayloadMcpTransportError("private URL"), "unreachable"),
    ],
)
def test_payload_mcp_probe_sanitizes_dependency_errors(error, reason):
    checks = _check(PayloadMcpReadinessProbe(StubCaller(error=error)))

    assert {check.reason for check in checks} == {reason}
    assert "private" not in str([check.as_dict() for check in checks])


def test_payload_mcp_probe_limits_dependency_wait_time():
    class BlockingCaller:
        async def list_tools(self):
            await asyncio.Event().wait()

    checks = _check(PayloadMcpReadinessProbe(BlockingCaller(), timeout_seconds=0))

    assert {check.reason for check in checks} == {"unreachable"}


def test_rag_probe_reports_existing_initialization_state():
    assert _check(RagReadinessProbe(StubRag(False)))[0].as_dict() == {
        "status": "not_ready",
        "required": True,
        "reason": "not_initialized",
    }


def test_platform_probe_retains_only_non_secret_configuration_state():
    configuration = PlatformConfiguration.from_values(
        page_access_token="private-page-token",
        facebook_verify_token="private-verify-token",
        line_channel_access_token="",
        line_channel_secret="private-line-secret",
        discord_bot_token="private-discord-token",
        discord_log_channel_id="123",
        staff_notification_channel_id="456",
        allowed_discord_channels=["789"],
        allowed_line_groups=["private-group-a", "private-group-b"],
    )

    check = _check(PlatformReadinessProbe(configuration))[0]
    serialized = str(check.as_dict())

    assert check.ready is False
    assert check.required is False
    assert check.details["allowed_line_group_count"] == 2
    assert "private" not in serialized
