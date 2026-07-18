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
from pydantic import ValidationError

from ian.domain.members import (
    MemberDataError,
    MemberTier,
    Membership,
    MembershipIntegrityError,
    Platform,
    User,
    normalize_email,
    normalize_personal_prompt,
    normalize_subscribe,
)


TPE = timezone(timedelta(hours=8))
NOW = datetime(2026, 7, 18, 12, tzinfo=TPE)


def membership(
    *,
    membership_id: int = 1,
    tier: int = 1,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> Membership:
    return Membership(
        id=membership_id,
        user=10,
        tier=tier,
        start_at=start_at or NOW - timedelta(days=1),
        end_at=end_at,
    )


def user(*, memberships: list[Membership] | None = None, subscribe=None) -> User:
    return User(
        id=10,
        name="Test User",
        email="test@example.test",
        emailVerified=True,
        discord_acc_id="discord-10",
        fb_acc_id="fb-10",
        line_acc_id="line-10",
        subscribe=subscribe,
        memberships=memberships or [],
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("discord", "discord"),
        (" LINE,discord, fb,LINE ", "discord,fb,line"),
    ],
)
def test_normalize_subscribe_canonicalizes_supported_platforms(raw, expected):
    assert normalize_subscribe(raw) == expected


@pytest.mark.parametrize("raw", ["", " ", "discord,", "slack", "fb,,line"])
def test_normalize_subscribe_rejects_invalid_values(raw):
    with pytest.raises(MemberDataError):
        normalize_subscribe(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Discord", Platform.DISCORD),
        ("facebook", Platform.FB),
        ("FB", Platform.FB),
        ("LINE", Platform.LINE),
    ],
)
def test_platform_parse_accepts_gateway_names(raw, expected):
    assert Platform.parse(raw) is expected


def test_platform_parse_rejects_unknown_platform():
    with pytest.raises(MemberDataError):
        Platform.parse("slack")


def test_membership_requires_timezone():
    with pytest.raises(ValidationError):
        membership(start_at=datetime(2026, 7, 18, 12))


def test_effective_tier_uses_active_membership_and_tier_labels():
    member = user(memberships=[membership(tier=3)])

    assert member.effective_tier(NOW) is MemberTier.PROJECT
    assert member.member_role(NOW) == "專案實作"


@pytest.mark.parametrize(
    "item",
    [
        membership(tier=0),
        membership(start_at=NOW + timedelta(seconds=1)),
        membership(end_at=NOW - timedelta(seconds=1)),
    ],
)
def test_effective_tier_is_zero_for_nonmember_or_inactive_membership(item):
    assert user(memberships=[item]).effective_tier(NOW) is MemberTier.NON_MEMBER


def test_end_at_null_is_unbounded_and_end_at_is_inclusive():
    assert membership(end_at=None).is_active(NOW)
    assert membership(end_at=NOW).is_active(NOW)


def test_multiple_active_memberships_fail_closed():
    member = user(
        memberships=[membership(membership_id=1), membership(membership_id=2)]
    )

    with pytest.raises(MembershipIntegrityError):
        member.effective_tier(NOW)


def test_user_normalizes_subscribe_and_exposes_platforms():
    member = user(subscribe=" line,discord,fb ")

    assert member.subscribe == "discord,fb,line"
    assert member.subscribed_platforms() == (
        Platform.DISCORD,
        Platform.FB,
        Platform.LINE,
    )


def test_normalize_email_lowercases_complete_address():
    assert normalize_email(" USER.Name@Example.COM ") == "user.name@example.com"


def test_normalize_personal_prompt_strips_and_truncates_to_limit():
    assert normalize_personal_prompt(f"  {'a' * 101}  ") == "a" * 100
