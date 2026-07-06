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

from datetime import datetime

from ian.config import TZ_TPE


TIER_ROLE_MAP = {
    "STAFF": "幹部",
    "VIP": "VIP 社員",
}

PLATFORM_FIELD_MAP = {
    "Discord": "discord_acc_id",
    "FB": "fb_acc_id",
    "LINE": "line_acc_id",
}

VALID_SUBSCRIBE_PLATFORMS = {"discord"}
SUBSCRIBE_PLATFORM_FIELD = {
    "discord": "discord_acc_id",
}
PERSONAL_PROMPT_MAX_LEN = 100


def is_valid_member(member: dict, now: datetime | None = None) -> bool:
    valid_date_str = member.get("valid_date", "")
    if not valid_date_str:
        return False
    try:
        valid_date = datetime.fromisoformat(valid_date_str.replace("Z", "+00:00"))
        current = now or datetime.now(TZ_TPE)
        return current <= valid_date
    except (ValueError, TypeError):
        return False


def get_role_from_tier(tier: str) -> str:
    if not tier:
        return "社員"
    return TIER_ROLE_MAP.get(tier, tier)


def platform_field(platform: str) -> str | None:
    return PLATFORM_FIELD_MAP.get(platform)


def normalize_email(email: str) -> str:
    email = email.strip()
    if "@" not in email:
        return email.lower()
    local, domain = email.rsplit("@", 1)
    return f"{local.lower()}@{domain}"


def parse_subscribe_platforms(subscribe_str: str) -> list[str]:
    raw_platforms = [p.strip().lower() for p in subscribe_str.split(",") if p.strip()]
    return sorted(set(raw_platforms))


def invalid_subscribe_platforms(subscribe_str: str) -> list[str]:
    raw_platforms = [p.strip().lower() for p in subscribe_str.split(",") if p.strip()]
    return [p for p in raw_platforms if p not in VALID_SUBSCRIBE_PLATFORMS]


def normalize_personal_prompt(prompt_text: str) -> str:
    return prompt_text.strip()[:PERSONAL_PROMPT_MAX_LEN]
