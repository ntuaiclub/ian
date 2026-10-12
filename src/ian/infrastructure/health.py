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
from dataclasses import dataclass
import time
from typing import Protocol

from ian.application.health import ReadinessCheck
from ian.application.metrics import ApplicationMetrics, NO_OP_METRICS
from ian.application.rag import RagService
from ian.infrastructure.payload_mcp.client import (
    McpToolCaller,
    PayloadMcpConfigurationError,
    PayloadMcpError,
)


MEMBER_DATA_TOOLS = frozenset({"findUsers", "findMemberships", "updateUsers"})
COURSE_DATA_TOOLS = frozenset({"findEvents"})


class ToolCapabilityCaller(Protocol):
    async def list_tools(self) -> set[str]: ...


class PayloadMcpReadinessProbe:
    def __init__(
        self,
        caller: McpToolCaller,
        timeout_seconds: float = 3.0,
        metrics: ApplicationMetrics = NO_OP_METRICS,
    ):
        self.caller = caller
        self.timeout_seconds = timeout_seconds
        self.metrics = metrics

    async def check(self) -> tuple[ReadinessCheck, ...]:
        started_at = time.monotonic()
        try:
            async with asyncio.timeout(self.timeout_seconds):
                tools = await self.caller.list_tools()
        except PayloadMcpConfigurationError:
            self._record_check(started_at, "not_ready")
            return self._failed_checks("missing_configuration")
        except (PayloadMcpError, TimeoutError):
            self._record_check(started_at, "not_ready")
            return self._failed_checks("unreachable")

        ready = MEMBER_DATA_TOOLS.union(COURSE_DATA_TOOLS).issubset(tools)
        self._record_check(started_at, "ready" if ready else "not_ready")
        return (
            self._tool_check("member_data", MEMBER_DATA_TOOLS, tools),
            self._tool_check("course_data", COURSE_DATA_TOOLS, tools),
        )

    def _record_check(self, started_at: float, outcome: str) -> None:
        self.metrics.record_dependency_check(
            "payload_mcp",
            outcome,
            time.monotonic() - started_at,
        )

    @staticmethod
    def _failed_checks(reason: str) -> tuple[ReadinessCheck, ...]:
        return (
            ReadinessCheck("member_data", ready=False, reason=reason),
            ReadinessCheck("course_data", ready=False, reason=reason),
        )

    @staticmethod
    def _tool_check(
        name: str,
        required_tools: frozenset[str],
        available_tools: set[str],
    ) -> ReadinessCheck:
        missing_count = len(required_tools - available_tools)
        return ReadinessCheck(
            name,
            ready=missing_count == 0,
            reason="missing_tools" if missing_count else None,
            details={"source": "payload_mcp", "missing_tool_count": missing_count},
        )


class RagReadinessProbe:
    def __init__(
        self,
        rag: RagService,
        metrics: ApplicationMetrics = NO_OP_METRICS,
    ):
        self.rag = rag
        self.metrics = metrics

    async def check(self) -> tuple[ReadinessCheck, ...]:
        started_at = time.monotonic()
        initialized = self.rag.is_initialized()
        self.metrics.record_dependency_check(
            "rag",
            "ready" if initialized else "not_ready",
            time.monotonic() - started_at,
        )
        return (
            ReadinessCheck(
                "rag",
                ready=initialized,
                reason=None if initialized else "not_initialized",
            ),
        )


@dataclass(frozen=True)
class PlatformConfiguration:
    facebook_configured: bool
    line_configured: bool
    discord_configured: bool
    discord_log_channel_configured: bool
    staff_notification_channel_configured: bool
    allowed_discord_channel_count: int
    allowed_line_group_count: int

    @classmethod
    def from_values(
        cls,
        *,
        page_access_token: str,
        facebook_verify_token: str,
        line_channel_access_token: str,
        line_channel_secret: str,
        discord_bot_token: str,
        discord_log_channel_id: str,
        staff_notification_channel_id: str,
        allowed_discord_channels: list[str],
        allowed_line_groups: list[str],
    ) -> "PlatformConfiguration":
        return cls(
            facebook_configured=bool(page_access_token and facebook_verify_token),
            line_configured=bool(
                line_channel_access_token and line_channel_secret
            ),
            discord_configured=bool(discord_bot_token),
            discord_log_channel_configured=bool(discord_log_channel_id),
            staff_notification_channel_configured=bool(
                staff_notification_channel_id
            ),
            allowed_discord_channel_count=len(allowed_discord_channels),
            allowed_line_group_count=len(allowed_line_groups),
        )

    def webhook_state(self, enabled_platforms: set[str]) -> dict[str, dict[str, bool]]:
        return {
            "Facebook": {
                "enabled": "Facebook" in enabled_platforms,
                "configured": self.facebook_configured,
            },
            "LINE": {
                "enabled": "LINE" in enabled_platforms,
                "configured": self.line_configured,
            },
        }


def build_platform_configuration() -> PlatformConfiguration:
    from ian.config import (
        ALLOWED_DISCORD_CHANNELS,
        DISCORD_BOT_TOKEN,
        DISCORD_LOG_CHANNEL_ID,
        FB_VERIFY_TOKEN,
        LINE_ALLOWED_GROUPS,
        LINE_CHANNEL_ACCESS_TOKEN,
        LINE_CHANNEL_SECRET,
        PAGE_ACCESS_TOKEN,
        STAFF_NOTIFICATION_CHANNEL_ID,
    )

    return PlatformConfiguration.from_values(
        page_access_token=PAGE_ACCESS_TOKEN,
        facebook_verify_token=FB_VERIFY_TOKEN,
        line_channel_access_token=LINE_CHANNEL_ACCESS_TOKEN,
        line_channel_secret=LINE_CHANNEL_SECRET,
        discord_bot_token=DISCORD_BOT_TOKEN,
        discord_log_channel_id=DISCORD_LOG_CHANNEL_ID,
        staff_notification_channel_id=STAFF_NOTIFICATION_CHANNEL_ID,
        allowed_discord_channels=ALLOWED_DISCORD_CHANNELS,
        allowed_line_groups=LINE_ALLOWED_GROUPS,
    )


class PlatformReadinessProbe:
    def __init__(
        self,
        configuration: PlatformConfiguration,
        metrics: ApplicationMetrics = NO_OP_METRICS,
    ):
        self.configuration = configuration
        self.metrics = metrics

    async def check(self) -> tuple[ReadinessCheck, ...]:
        started_at = time.monotonic()
        configuration = self.configuration
        configured = all(
            (
                configuration.facebook_configured,
                configuration.line_configured,
                configuration.discord_configured,
                configuration.discord_log_channel_configured,
                configuration.staff_notification_channel_configured,
            )
        )
        duration = time.monotonic() - started_at
        for dependency, ready in (
            ("facebook", configuration.facebook_configured),
            ("line", configuration.line_configured),
            ("discord", configuration.discord_configured),
        ):
            self.metrics.record_dependency_check(
                dependency,
                "ready" if ready else "not_ready",
                duration,
            )
        return (
            ReadinessCheck(
                "platforms",
                ready=configured,
                required=False,
                reason=None if configured else "missing_configuration",
                details={
                    "facebook_configured": configuration.facebook_configured,
                    "line_configured": configuration.line_configured,
                    "discord_configured": configuration.discord_configured,
                    "discord_log_channel_configured": (
                        configuration.discord_log_channel_configured
                    ),
                    "staff_notification_channel_configured": (
                        configuration.staff_notification_channel_configured
                    ),
                    "allowed_discord_channel_count": (
                        configuration.allowed_discord_channel_count
                    ),
                    "allowed_line_group_count": configuration.allowed_line_group_count,
                },
            ),
        )
