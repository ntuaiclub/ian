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

from ian.services import member_store


TPE = timezone(timedelta(hours=8))
FUTURE_VALID_DATE = datetime(2099, 1, 1, tzinfo=TPE).isoformat()
PAST_VALID_DATE = datetime(2000, 1, 1, tzinfo=TPE).isoformat()


def _valid_member(**overrides):
    member = {
        "id": "Alice",
        "email": "alice@example.com",
        "Tier": "",
        "valid_date": FUTURE_VALID_DATE,
        "discord_acc_id": "discord-1",
        "line_acc_id": "",
        "fb_acc_id": "",
        "subscribe": "",
        "personal_prompt": "",
    }
    member.update(overrides)
    return member


def test_lookup_member_with_reload_returns_initial_hit_without_reloading(monkeypatch):
    calls = []

    def fake_lookup(platform, account_id):
        calls.append(("lookup", platform, account_id))
        return _valid_member()

    def fake_load():
        calls.append(("load",))
        return True

    monkeypatch.setattr(member_store, "lookup_member_by_platform", fake_lookup)
    monkeypatch.setattr(member_store, "load_member_db", fake_load)

    member = member_store._lookup_member_with_reload("Discord", "discord-1")

    assert member["id"] == "Alice"
    assert calls == [("lookup", "Discord", "discord-1")]


def test_lookup_member_with_reload_returns_reload_hit(monkeypatch):
    calls = []
    lookups = iter([None, _valid_member(id="Bob")])

    def fake_lookup(platform, account_id):
        calls.append(("lookup", platform, account_id))
        return next(lookups)

    def fake_load():
        calls.append(("load",))
        return True

    monkeypatch.setattr(member_store, "lookup_member_by_platform", fake_lookup)
    monkeypatch.setattr(member_store, "load_member_db", fake_load)

    member = member_store._lookup_member_with_reload("Discord", "discord-1")

    assert member["id"] == "Bob"
    assert calls == [
        ("lookup", "Discord", "discord-1"),
        ("load",),
        ("lookup", "Discord", "discord-1"),
    ]


def test_lookup_member_with_reload_returns_none_after_reload_miss(monkeypatch):
    calls = []

    def fake_lookup(platform, account_id):
        calls.append(("lookup", platform, account_id))
        return None

    def fake_load():
        calls.append(("load",))
        return True

    monkeypatch.setattr(member_store, "lookup_member_by_platform", fake_lookup)
    monkeypatch.setattr(member_store, "load_member_db", fake_load)

    assert member_store._lookup_member_with_reload("Discord", "missing") is None
    assert calls == [
        ("lookup", "Discord", "missing"),
        ("load",),
        ("lookup", "Discord", "missing"),
    ]


@pytest.mark.parametrize(
    ("member", "expected_role"),
    [
        (None, "非社員"),
        (_valid_member(Tier="STAFF"), "幹部"),
        (_valid_member(Tier="VIP"), "VIP 社員"),
        (_valid_member(Tier=""), "社員"),
        (
            _valid_member(valid_date=PAST_VALID_DATE),
            "非社員（已過期）",
        ),
    ],
)
def test_get_member_role_handles_member_status_and_tiers(
    monkeypatch, member, expected_role
):
    calls = []

    def fake_lookup_with_reload(platform, account_id):
        calls.append((platform, account_id))
        return member

    monkeypatch.setattr(member_store, "_lookup_member_with_reload", fake_lookup_with_reload)

    assert member_store.get_member_role("Discord", "discord-1") == expected_role
    assert calls == [("Discord", "discord-1")]


@pytest.mark.parametrize(
    (
        "member",
        "subscribe_str",
        "expected_result",
        "expected_update",
    ),
    [
        (
            None,
            "discord",
            {"success": False, "message": "找不到您的社員資料，請先透過 Email 綁定身分。"},
            None,
        ),
        (
            _valid_member(valid_date=PAST_VALID_DATE),
            "discord",
            {"success": False, "message": "您的社員資格已過期，無法設定訂閱。"},
            None,
        ),
        (
            _valid_member(subscribe="discord"),
            "",
            {"success": True, "message": "已取消所有通知訂閱。"},
            ("alice@example.com", "subscribe", ""),
        ),
        (
            _valid_member(subscribe="discord"),
            "   ",
            {"success": True, "message": "已取消所有通知訂閱。"},
            ("alice@example.com", "subscribe", ""),
        ),
        (
            _valid_member(),
            ",,, line ,,",
            {"success": False, "message": "不支援的平台: line。目前僅支援: discord"},
            None,
        ),
        (
            _valid_member(discord_acc_id=""),
            "discord",
            {
                "success": False,
                "message": "您尚未綁定 discord 帳號，請先綁定後再訂閱該平台的通知。",
            },
            None,
        ),
        (
            _valid_member(discord_acc_id="0"),
            "discord",
            {
                "success": False,
                "message": "您尚未綁定 discord 帳號，請先綁定後再訂閱該平台的通知。",
            },
            None,
        ),
        (
            _valid_member(discord_acc_id="discord-1"),
            " Discord, discord ",
            {"success": True, "message": "訂閱設定已更新！您將在以下平台收到每日課程通知：discord"},
            ("alice@example.com", "subscribe", "discord"),
        ),
    ],
)
def test_update_subscribe_handles_edge_cases_without_real_db_or_api(
    monkeypatch,
    member,
    subscribe_str,
    expected_result,
    expected_update,
):
    lookup_calls = []
    update_calls = []

    def fake_lookup_with_reload(platform, account_id):
        lookup_calls.append((platform, account_id))
        return member

    def fake_update_member_field(email, field, value):
        update_calls.append((email, field, value))
        return {"success": True, "message": "更新成功"}

    monkeypatch.setattr(member_store, "_lookup_member_with_reload", fake_lookup_with_reload)
    monkeypatch.setattr(member_store, "_update_member_field", fake_update_member_field)

    result = member_store.update_subscribe("Discord", "discord-1", subscribe_str)

    assert result == expected_result
    assert lookup_calls == [("Discord", "discord-1")]
    assert update_calls == ([] if expected_update is None else [expected_update])
