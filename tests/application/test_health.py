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

from ian.application.health import HealthService, ReadinessCheck


class StubProbe:
    def __init__(self, *checks: ReadinessCheck):
        self.checks = checks

    async def check(self):
        return self.checks


def _readiness(*probes: StubProbe):
    return asyncio.run(HealthService(probes).readiness())


def test_readiness_report_is_ready_when_all_checks_pass():
    report = _readiness(
        StubProbe(ReadinessCheck("member_data", ready=True)),
        StubProbe(ReadinessCheck("rag", ready=True)),
    )

    assert report.ready is True
    assert report.as_dict() == {
        "status": "ready",
        "checks": {
            "member_data": {"status": "ready", "required": True},
            "rag": {"status": "ready", "required": True},
        },
    }


def test_readiness_report_is_not_ready_when_required_check_fails():
    report = _readiness(
        StubProbe(
            ReadinessCheck(
                "course_data",
                ready=False,
                reason="unreachable",
            )
        )
    )

    assert report.ready is False
    assert report.status == "not_ready"


def test_readiness_report_is_degraded_when_optional_check_fails():
    report = _readiness(
        StubProbe(ReadinessCheck("rag", ready=True)),
        StubProbe(
            ReadinessCheck(
                "platforms",
                ready=False,
                required=False,
                reason="missing_configuration",
                details={"facebook_configured": False},
            )
        ),
    )

    assert report.ready is True
    assert report.as_dict()["status"] == "degraded"
