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

import pytest

from ian.application.checkins import CheckinLinkService


class MembersStub:
    def __init__(self, member=None):
        self.member = member

    async def find_user_by_platform(self, platform, account_id):
        assert platform == "Discord"
        assert account_id == "account-1"
        return self.member


@pytest.mark.asyncio
async def test_member_identity_takes_precedence_over_supplied_values():
    service = CheckinLinkService(
        MembersStub(
            SimpleNamespace(name="王 小明", email="member+test@example.test")
        )
    )

    result = await service.generate(
        "Discord",
        "account-1",
        "ignored",
        "ignored@example.test",
    )

    assert result.status == "member"
    assert result.name == "王 小明"
    assert "name=%E7%8E%8B%20%E5%B0%8F%E6%98%8E" in result.url
    assert "id=member%2Btest%40example.test" in result.url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "email", "status"),
    [
        ("", "", "missing_identity"),
        ("Visitor", "invalid", "invalid_email"),
        ("Guest User", "guest@example.test", "guest"),
    ],
)
async def test_guest_validation(name, email, status):
    result = await CheckinLinkService(MembersStub()).generate(
        "Discord",
        "account-1",
        name,
        email,
    )

    assert result.status == status
