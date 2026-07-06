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

from ian.domain.members import (
    get_role_from_tier,
    invalid_subscribe_platforms,
    is_valid_member,
    normalize_email,
    normalize_personal_prompt,
    parse_subscribe_platforms,
    platform_field,
)


TPE = timezone(timedelta(hours=8))
NOW = datetime(2026, 3, 7, tzinfo=TPE)


@pytest.mark.parametrize(
    ("member", "expected"),
    [
        ({"valid_date": "2026-03-08T00:00:00+08:00"}, True),
        ({"valid_date": "2026-03-07T00:00:00+08:00"}, True),
        ({"valid_date": "2026-03-06T23:59:59+08:00"}, False),
        ({"valid_date": "2026-03-07T00:00:00Z"}, True),
        ({"valid_date": ""}, False),
        ({"valid_date": "not-a-date"}, False),
        ({"valid_date": None}, False),
        ({}, False),
    ],
)
def test_member_validity_handles_edge_cases(member, expected):
    assert is_valid_member(member, now=NOW) is expected


@pytest.mark.parametrize(
    ("tier", "expected"),
    [
        ("STAFF", "幹部"),
        ("VIP", "VIP 社員"),
        ("", "社員"),
        ("NORMAL", "NORMAL"),
    ],
)
def test_role_mapping_handles_known_and_custom_tiers(tier, expected):
    assert get_role_from_tier(tier) == expected


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("Discord", "discord_acc_id"),
        ("FB", "fb_acc_id"),
        ("LINE", "line_acc_id"),
        ("Slack", None),
        ("discord", None),
        ("", None),
    ],
)
def test_platform_field_mapping_handles_supported_and_unknown_platforms(
    platform, expected
):
    assert platform_field(platform) == expected


def test_normalize_email_lowercases_local_part_only():
    assert normalize_email(" USER.Name@Example.COM ") == "user.name@Example.COM"


@pytest.mark.parametrize(
    ("subscribe_str", "expected"),
    [
        (" Discord, discord,  DISCORD ", ["discord"]),
        (" ", []),
        ("", []),
        (",,,", []),
        ("discord,line, discord", ["discord", "line"]),
        ("LINE, discord,fb", ["discord", "fb", "line"]),
    ],
)
def test_parse_subscribe_platforms_trims_lowercases_deduplicates_and_sorts(
    subscribe_str, expected
):
    assert parse_subscribe_platforms(subscribe_str) == expected


def test_invalid_subscribe_platforms_preserves_invalid_entries_for_messages():
    assert invalid_subscribe_platforms(" Discord, line, fb, LINE ") == [
        "line",
        "fb",
        "line",
    ]


def test_normalize_personal_prompt_strips_and_truncates_to_limit():
    assert normalize_personal_prompt(f"  {'a' * 101}  ") == "a" * 100
