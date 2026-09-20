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

import pytest

from ian.application.agent import AgentRequest, AgentService


class AgentAdapterStub:
    def __init__(self, response="正常回覆"):
        self.response = response
        self.requests = []
        self.cleared = []
        self.startup_calls = 0

    async def generate(self, request):
        self.requests.append(request)
        return self.response

    async def clear(self, session_id):
        self.cleared.append(session_id)

    async def startup(self):
        self.startup_calls += 1


def request():
    return AgentRequest(
        session_id="session-1",
        user_name="Ian User",
        question="社課時間？",
        user_role=["社員"],
        timestamp=123.0,
        channel_id="channel-1",
        platform="Discord",
        account_id="account-1",
    )


@pytest.mark.asyncio
async def test_agent_service_returns_normal_response():
    adapter = AgentAdapterStub()
    service = AgentService(adapter)

    result = await service.handle(request())

    assert result.text == "正常回覆"
    assert result.should_reply is True
    assert result.reaction_emoji is None
    assert result.reason is None
    assert adapter.requests == [request()]


@pytest.mark.asyncio
async def test_agent_service_parses_no_response_reaction():
    service = AgentService(AgentAdapterStub("[NO_RESPONSE:🙏]"))

    result = await service.handle(request())

    assert result.should_reply is False
    assert result.reaction_emoji == "🙏"


@pytest.mark.asyncio
async def test_agent_service_identifies_usage_limit():
    service = AgentService(AgentAdapterStub("😌 已達今日使用上限，明天再來。"))

    result = await service.handle(request())

    assert result.reason == "usage_limit"


@pytest.mark.asyncio
async def test_agent_service_delegates_clear_and_startup():
    adapter = AgentAdapterStub()
    service = AgentService(adapter)

    await service.startup()
    await service.clear("session-1")

    assert adapter.startup_calls == 1
    assert adapter.cleared == ["session-1"]
