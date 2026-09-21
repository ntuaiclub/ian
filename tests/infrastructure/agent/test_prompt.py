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

from ian.infrastructure.agent.prompt import SYS_PROMPT


def test_event_registration_and_checkin_direct_users_to_member_website():
    assert "https://ntuai.dev/events" in SYS_PROMPT
    for intent in (
        "活動報名",
        "取消報名",
        "registration",
        "cancellation",
        "enrollment",
        "check-in",
        "簽到",
    ):
        assert intent in SYS_PROMPT


def test_event_registration_does_not_collect_identity_or_claim_completion():
    assert "此流程不要索取使用者的姓名、Email 或其他個人資料" in SYS_PROMPT
    assert "不要宣稱 Ian 可以代辦、確認或完成這些操作" in SYS_PROMPT
    assert "使用者必須自行在該網站完成活動報名與簽到" in SYS_PROMPT


def test_agent_prompt_keeps_member_identity_binding_separate():
    assert "bind_email" in SYS_PROMPT
    assert "只有在使用者明確要求綁定社員身分時" in SYS_PROMPT
