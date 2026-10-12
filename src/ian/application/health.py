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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol


HealthDetail = bool | int | str


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    ready: bool
    required: bool = True
    reason: str | None = None
    details: Mapping[str, HealthDetail] = field(default_factory=dict)

    def as_dict(self) -> dict[str, HealthDetail]:
        result: dict[str, HealthDetail] = {
            "status": "ready" if self.ready else "not_ready",
            "required": self.required,
            **self.details,
        }
        if self.reason is not None:
            result["reason"] = self.reason
        return result


@dataclass(frozen=True)
class ReadinessReport:
    checks: tuple[ReadinessCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.ready for check in self.checks if check.required)

    @property
    def status(self) -> str:
        if not self.ready:
            return "not_ready"
        if any(not check.ready for check in self.checks):
            return "degraded"
        return "ready"

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "checks": {check.name: check.as_dict() for check in self.checks},
        }


class ReadinessProbe(Protocol):
    async def check(self) -> Sequence[ReadinessCheck]: ...


class HealthService:
    def __init__(self, probes: Sequence[ReadinessProbe]):
        self.probes = tuple(probes)

    async def readiness(self) -> ReadinessReport:
        checks = [check for probe in self.probes for check in await probe.check()]
        return ReadinessReport(tuple(checks))
