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

from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ian.config import TZ_TPE


_VALID_SUBSCRIBE_PLATFORMS = {"discord", "fb", "line"}
PERSONAL_PROMPT_MAX_LEN = 100
SUBSCRIBE_PLATFORM_ORDER = ("discord", "fb", "line")


class MemberDataError(ValueError):
    """Raised when MCP member data violates the domain contract."""


class MembershipIntegrityError(MemberDataError):
    """Raised when a user has ambiguous active memberships."""


class Platform(StrEnum):
    DISCORD = "discord"
    FB = "fb"
    LINE = "line"

    @classmethod
    def parse(cls, value: str | "Platform") -> "Platform":
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().lower()
        aliases = {
            "discord": cls.DISCORD,
            "fb": cls.FB,
            "facebook": cls.FB,
            "line": cls.LINE,
        }
        try:
            return aliases[normalized]
        except KeyError as error:
            raise MemberDataError(f"不支援的平台: {value}") from error

    @property
    def account_field(self) -> str:
        return {
            Platform.DISCORD: "discord_acc_id",
            Platform.FB: "fb_acc_id",
            Platform.LINE: "line_acc_id",
        }[self]


class MemberTier(IntEnum):
    NON_MEMBER = 0
    LECTURE_EXPLORATION = 1
    HANDS_ON = 2
    PROJECT = 3

    @property
    def label(self) -> str:
        return {
            MemberTier.NON_MEMBER: "非社員",
            MemberTier.LECTURE_EXPLORATION: "講座探索",
            MemberTier.HANDS_ON: "動手實作",
            MemberTier.PROJECT: "專案實作",
        }[self]


def normalize_subscribe(value: str | None) -> str | None:
    """Normalize a comma-separated MCP subscription string."""
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        raise MemberDataError("subscribe 不可為空字串，取消訂閱請使用 null")

    parts = raw.split(",")
    normalized = [part.strip().lower() for part in parts]
    if any(not part for part in normalized):
        raise MemberDataError("subscribe 不可包含空的平台")

    invalid = sorted(
        {part for part in normalized if part not in _VALID_SUBSCRIBE_PLATFORMS}
    )
    if invalid:
        raise MemberDataError(f"不支援的訂閱平台: {', '.join(invalid)}")

    selected = set(normalized)
    return ",".join(
        platform for platform in SUBSCRIBE_PLATFORM_ORDER if platform in selected
    )


class Membership(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    user: int
    tier: int = Field(ge=0, le=3)
    start_at: datetime
    end_at: datetime | None = None

    @field_validator("start_at", "end_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("membership datetime must include a timezone")
        return value

    def is_active(self, now: datetime | None = None) -> bool:
        if self.tier == MemberTier.NON_MEMBER:
            return False
        current = now or datetime.now(TZ_TPE)
        return self.start_at <= current and (
            self.end_at is None or current <= self.end_at
        )


class User(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    email: str
    emailVerified: bool
    discord_acc_id: str | None = None
    fb_acc_id: str | None = None
    line_acc_id: str | None = None
    subscribe: str | None = None
    personal_prompt: str | None = None
    memberships: list[Membership] = Field(default_factory=list)

    @field_validator("subscribe")
    @classmethod
    def validate_subscribe(cls, value: str | None) -> str | None:
        return normalize_subscribe(value)

    def active_membership(self, now: datetime | None = None) -> Membership | None:
        active = [
            membership for membership in self.memberships if membership.is_active(now)
        ]
        if len(active) > 1:
            raise MembershipIntegrityError(
                f"user {self.id} has multiple active memberships"
            )
        return active[0] if active else None

    def effective_tier(self, now: datetime | None = None) -> MemberTier:
        membership = self.active_membership(now)
        return MemberTier(membership.tier) if membership else MemberTier.NON_MEMBER

    def member_role(self, now: datetime | None = None) -> str:
        return self.effective_tier(now).label

    def subscribed_platforms(self) -> tuple[Platform, ...]:
        if self.subscribe is None:
            return ()
        return tuple(Platform(part) for part in self.subscribe.split(","))


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_personal_prompt(prompt_text: str) -> str:
    return prompt_text.strip()[:PERSONAL_PROMPT_MAX_LEN]
