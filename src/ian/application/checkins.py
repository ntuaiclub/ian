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

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

from ian.application.members import MemberService


@dataclass(frozen=True)
class CheckinLinkResult:
    status: Literal["member", "guest", "missing_identity", "invalid_email"]
    name: str = ""
    url: str = ""


class CheckinLinkService:
    def __init__(self, members: MemberService):
        self.members = members

    @staticmethod
    def _build_url(name: str, email: str) -> str:
        return (
            "https://watsonshih.github.io/QuickRecord/user.html?"
            f"name={quote(name)}&id={quote(email)}"
        )

    async def generate(
        self,
        platform: str,
        account_id: str,
        name: str = "",
        email: str = "",
    ) -> CheckinLinkResult:
        member = await self.members.find_user_by_platform(platform, account_id)
        if member and member.name and member.email:
            return CheckinLinkResult(
                "member",
                member.name,
                self._build_url(member.name, member.email),
            )
        if not name or not email:
            return CheckinLinkResult("missing_identity")
        if "@" not in email:
            return CheckinLinkResult("invalid_email")
        return CheckinLinkResult("guest", name, self._build_url(name, email))
