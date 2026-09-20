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

from types import SimpleNamespace

import ian.bootstrap as bootstrap
from ian.bootstrap import build_application
from ian.infrastructure.payload_mcp.event_repository import (
    PayloadMcpEventRepository,
)
from ian.infrastructure.payload_mcp.member_repository import (
    PayloadMcpMemberRepository,
)


class FakeCaller:
    async def call_tool(self, name, arguments):
        raise AssertionError("composition must not call MCP")


class FakeSender:
    async def send(self, recipient, message):
        raise AssertionError("composition must not send notifications")


def test_build_application_composes_dependencies_without_io():
    application = build_application(FakeCaller(), FakeSender())

    assert isinstance(application.events.repository, PayloadMcpEventRepository)
    assert isinstance(application.members.repository, PayloadMcpMemberRepository)
    assert application.checkins.members is application.members
    assert application.reminders.events is application.events
    assert application.reminders.members is application.members
    assert application.member_notifications.events is application.events
    assert application.member_notifications.members is application.members


def test_get_application_builds_default_graph_once(monkeypatch):
    application = SimpleNamespace()
    calls = []
    monkeypatch.setattr(bootstrap, "_default_application", None)
    monkeypatch.setattr(
        bootstrap,
        "build_application",
        lambda: calls.append(True) or application,
    )

    assert bootstrap.get_application() is application
    assert bootstrap.get_application() is application
    assert calls == [True]
