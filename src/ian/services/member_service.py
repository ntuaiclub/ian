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
from datetime import datetime
from typing import Protocol

from ian.config import (
    MEMBER_MCP_API_KEY,
    MEMBER_MCP_TIMEOUT_SECONDS,
    MEMBER_MCP_URL,
)
from ian.domain.members import (
    MemberDataError,
    MemberTier,
    Platform,
    User,
    normalize_email,
    normalize_personal_prompt,
    normalize_subscribe,
)
from ian.services.member_mcp_repository import (
    MemberMcpRepository,
    StreamableHttpMcpToolCaller,
)


class MemberRepository(Protocol):
    async def find_user_by_id(self, user_id: int) -> User | None: ...

    async def find_user_by_email(self, email: str) -> User | None: ...

    async def find_user_by_platform(
        self,
        platform: Platform,
        account_id: str,
    ) -> User | None: ...

    async def list_users_with_memberships(self) -> list[User]: ...

    async def update_user(
        self,
        user_id: int,
        fields: dict[str, str | None],
    ) -> User: ...


@dataclass(frozen=True)
class OperationResult:
    success: bool
    message: str


@dataclass(frozen=True)
class ReminderRecipient:
    user_id: int
    name: str
    email: str
    platform: Platform
    account_id: str
    tier: MemberTier


class MemberService:
    def __init__(self, repository: MemberRepository):
        self.repository = repository

    async def find_user_by_platform(
        self,
        platform: str | Platform,
        account_id: str,
    ) -> User | None:
        parsed_platform = Platform.parse(platform)
        normalized_account_id = account_id.strip()
        if not normalized_account_id:
            return None
        return await self.repository.find_user_by_platform(
            parsed_platform,
            normalized_account_id,
        )

    async def find_user_by_email(self, email: str) -> User | None:
        normalized = normalize_email(email)
        if not normalized or "@" not in normalized:
            return None
        return await self.repository.find_user_by_email(normalized)

    async def get_member_role(
        self,
        platform: str | Platform,
        account_id: str,
        now: datetime | None = None,
    ) -> str:
        user = await self.find_user_by_platform(platform, account_id)
        return user.member_role(now) if user else MemberTier.NON_MEMBER.label

    async def bind_user_platform(
        self,
        email: str,
        platform: str | Platform,
        account_id: str,
    ) -> OperationResult:
        try:
            parsed_platform = Platform.parse(platform)
        except MemberDataError as error:
            return OperationResult(False, str(error))
        normalized_account_id = account_id.strip()
        if not normalized_account_id:
            return OperationResult(False, "無法取得您的帳號 ID")

        user = await self.find_user_by_email(email)
        if user is None:
            return OperationResult(False, "找不到此 Email 對應的社員資料。")
        if not user.emailVerified:
            return OperationResult(False, "此 Email 尚未完成驗證，無法綁定。")
        if user.effective_tier() == MemberTier.NON_MEMBER:
            return OperationResult(False, "此 Email 的社員身分無效或已過期，無法綁定。")

        field = parsed_platform.account_field
        existing = getattr(user, field)
        if existing == normalized_account_id:
            return OperationResult(
                True,
                f"您的帳號已經綁定為{user.member_role()}「{user.name}」，無需重複綁定。",
            )
        if existing:
            return OperationResult(
                False,
                "此 Email 的平台帳號已綁定；如需換綁，請聯繫管理員。",
            )

        account_owner = await self.repository.find_user_by_platform(
            parsed_platform,
            normalized_account_id,
        )
        if account_owner is not None and account_owner.id != user.id:
            return OperationResult(
                False,
                "此平台帳號已綁定其他身分；如需處理，請聯繫管理員。",
            )

        updated = await self.repository.update_user(
            user.id,
            {field: normalized_account_id},
        )
        if getattr(updated, field) != normalized_account_id:
            return OperationResult(False, "平台帳號更新後驗證失敗，請稍後再試。")
        return OperationResult(
            True,
            f"綁定成功！已將您的 {parsed_platform.value} 帳號綁定為{updated.member_role()}「{updated.name}」。",
        )

    async def update_user_subscription(
        self,
        platform: str | Platform,
        account_id: str,
        subscribe: str | None,
    ) -> OperationResult:
        user = await self.find_user_by_platform(platform, account_id)
        if user is None:
            return OperationResult(False, "找不到您的社員資料，請先綁定身分。")
        if user.effective_tier() == MemberTier.NON_MEMBER:
            return OperationResult(False, "您的社員身分無效或已過期，無法設定訂閱。")

        try:
            normalized = normalize_subscribe(subscribe)
        except MemberDataError as error:
            return OperationResult(False, str(error))

        if normalized is not None:
            subscribed_platform = Platform(normalized)
            if not getattr(user, subscribed_platform.account_field):
                return OperationResult(
                    False,
                    f"您尚未綁定 {subscribed_platform.value} 帳號，無法訂閱。",
                )

        updated = await self.repository.update_user(
            user.id,
            {"subscribe": normalized},
        )
        if updated.subscribe != normalized:
            return OperationResult(False, "訂閱更新後驗證失敗，請稍後再試。")
        if normalized is None:
            return OperationResult(True, "已取消所有通知訂閱。")
        return OperationResult(
            True,
            f"訂閱設定已更新：{normalized}",
        )

    async def update_personal_prompt(
        self,
        platform: str | Platform,
        account_id: str,
        personal_prompt: str,
    ) -> OperationResult:
        user = await self.find_user_by_platform(platform, account_id)
        if user is None:
            return OperationResult(False, "找不到您的社員資料，無法更新個人備註。")

        normalized = normalize_personal_prompt(personal_prompt)
        stored_value = normalized or None
        updated = await self.repository.update_user(
            user.id,
            {"personal_prompt": stored_value},
        )
        if updated.personal_prompt != stored_value:
            return OperationResult(False, "個人備註更新後驗證失敗，請稍後再試。")
        return OperationResult(True, "已更新使用者個人備註。")

    async def list_reminder_recipients(
        self,
        now: datetime | None = None,
    ) -> list[ReminderRecipient]:
        recipients: list[ReminderRecipient] = []
        for user in await self.repository.list_users_with_memberships():
            tier = user.effective_tier(now)
            if tier == MemberTier.NON_MEMBER:
                continue
            subscribed_platform = user.subscribed_platform()
            if subscribed_platform is None:
                continue
            account_id = getattr(user, subscribed_platform.account_field)
            if not account_id:
                raise MemberDataError(
                    f"user {user.id} subscribes to an unbound platform"
                )
            recipients.append(
                ReminderRecipient(
                    user_id=user.id,
                    name=user.name,
                    email=user.email,
                    platform=subscribed_platform,
                    account_id=account_id,
                    tier=tier,
                )
            )
        return recipients


def create_member_service() -> MemberService:
    caller = StreamableHttpMcpToolCaller(
        MEMBER_MCP_URL,
        MEMBER_MCP_API_KEY,
        MEMBER_MCP_TIMEOUT_SECONDS,
    )
    return MemberService(MemberMcpRepository(caller))


member_service = create_member_service()
