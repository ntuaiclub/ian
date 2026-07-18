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

from datetime import datetime, timedelta, timezone

import pytest

from ian.domain.members import MemberDataError, Membership, Platform, User
from ian.services.member_service import MemberService


NOW = datetime(2026, 7, 18, 12, tzinfo=timezone.utc)


def make_user(
    *,
    user_id: int = 10,
    verified: bool = True,
    tier: int = 2,
    subscribe: str | None = None,
    discord_acc_id: str | None = "discord-10",
    fb_acc_id: str | None = "fb-10",
    line_acc_id: str | None = "line-10",
    personal_prompt: str | None = None,
) -> User:
    memberships = []
    if tier >= 0:
        memberships = [
            Membership(
                id=user_id + 100,
                user=user_id,
                tier=tier,
                start_at=NOW - timedelta(days=1),
                end_at=None,
            )
        ]
    return User(
        id=user_id,
        name=f"User {user_id}",
        email=f"user{user_id}@example.test",
        emailVerified=verified,
        discord_acc_id=discord_acc_id,
        fb_acc_id=fb_acc_id,
        line_acc_id=line_acc_id,
        subscribe=subscribe,
        personal_prompt=personal_prompt,
        memberships=memberships,
    )


class FakeRepository:
    def __init__(self, users: list[User]):
        self.users = {user.id: user for user in users}
        self.updates: list[tuple[int, dict[str, str | None]]] = []

    async def find_user_by_id(self, user_id: int):
        return self.users.get(user_id)

    async def find_user_by_email(self, email: str):
        return next((user for user in self.users.values() if user.email == email), None)

    async def find_user_by_platform(self, platform: Platform, account_id: str):
        return next(
            (
                user
                for user in self.users.values()
                if getattr(user, platform.account_field) == account_id
            ),
            None,
        )

    async def list_users_with_memberships(self):
        return list(self.users.values())

    async def update_user(self, user_id: int, fields: dict[str, str | None]):
        self.updates.append((user_id, fields))
        user = self.users[user_id].model_copy(update=fields)
        self.users[user_id] = user
        return user


@pytest.mark.asyncio
async def test_get_member_role_uses_effective_tier():
    service = MemberService(FakeRepository([make_user(tier=3)]))

    assert await service.get_member_role("Discord", "discord-10", NOW) == "專案實作"
    assert await service.get_member_role("Discord", "missing", NOW) == "非社員"


@pytest.mark.asyncio
async def test_bind_requires_verified_active_user():
    unverified = make_user(verified=False)
    expired = make_user(user_id=11, tier=0)
    repository = FakeRepository([unverified, expired])
    service = MemberService(repository)

    unverified_result = await service.bind_user_platform(
        unverified.email, "LINE", "new-line"
    )
    expired_result = await service.bind_user_platform(expired.email, "LINE", "new-line")

    assert not unverified_result.success
    assert "尚未完成驗證" in unverified_result.message
    assert not expired_result.success
    assert "無效或已過期" in expired_result.message
    assert repository.updates == []


@pytest.mark.asyncio
async def test_bind_prevents_rebinding_and_account_reuse():
    owner = make_user(line_acc_id="line-owner")
    other = make_user(user_id=11, line_acc_id="line-other")
    candidate = make_user(user_id=12, line_acc_id=None)
    repository = FakeRepository([owner, other, candidate])
    service = MemberService(repository)

    rebind = await service.bind_user_platform(owner.email, "LINE", "line-new")
    reused = await service.bind_user_platform(
        candidate.email,
        "LINE",
        "line-other",
    )

    assert not rebind.success
    assert "管理員" in rebind.message
    assert not reused.success


@pytest.mark.asyncio
async def test_bind_updates_unbound_platform_and_verifies_result():
    member = make_user(line_acc_id=None)
    repository = FakeRepository([member])
    service = MemberService(repository)

    result = await service.bind_user_platform(member.email, "LINE", "line-new")

    assert result.success
    assert repository.updates == [(member.id, {"line_acc_id": "line-new"})]


@pytest.mark.asyncio
async def test_subscription_requires_every_selected_platform_to_be_bound():
    member = make_user(line_acc_id=None)
    repository = FakeRepository([member])
    service = MemberService(repository)

    result = await service.update_user_subscription(
        "Discord", "discord-10", "discord,line"
    )

    assert not result.success
    assert "line" in result.message
    assert repository.updates == []


@pytest.mark.asyncio
async def test_subscription_normalizes_multiplatform_value_and_clears_with_none():
    repository = FakeRepository([make_user()])
    service = MemberService(repository)

    update = await service.update_user_subscription(
        "Discord", "discord-10", " line,discord,fb,line "
    )
    clear = await service.update_user_subscription("Discord", "discord-10", None)

    assert update.success
    assert clear.success
    assert repository.updates == [
        (10, {"subscribe": "discord,fb,line"}),
        (10, {"subscribe": None}),
    ]


@pytest.mark.asyncio
async def test_personal_prompt_is_trimmed_truncated_and_clearable():
    repository = FakeRepository([make_user()])
    service = MemberService(repository)

    update = await service.update_personal_prompt(
        "Discord", "discord-10", f"  {'x' * 101} "
    )
    clear = await service.update_personal_prompt("Discord", "discord-10", "  ")

    assert update.success
    assert clear.success
    assert repository.updates == [
        (10, {"personal_prompt": "x" * 100}),
        (10, {"personal_prompt": None}),
    ]


@pytest.mark.asyncio
async def test_reminder_recipients_expand_subscriptions_by_platform():
    subscribed = make_user(subscribe="discord,fb,line")
    nonmember = make_user(user_id=11, tier=0, subscribe="discord")
    service = MemberService(FakeRepository([subscribed, nonmember]))

    recipients = await service.list_reminder_recipients(NOW)

    assert [(item.platform, item.account_id) for item in recipients] == [
        (Platform.DISCORD, "discord-10"),
        (Platform.FB, "fb-10"),
        (Platform.LINE, "line-10"),
    ]


@pytest.mark.asyncio
async def test_reminder_recipients_fail_on_unbound_subscription():
    service = MemberService(
        FakeRepository([make_user(subscribe="line", line_acc_id=None)])
    )

    with pytest.raises(MemberDataError):
        await service.list_reminder_recipients(NOW)
