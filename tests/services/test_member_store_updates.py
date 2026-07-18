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

import json
from datetime import datetime, timedelta, timezone

import pytest

from ian.services import member_store
from ian.services.member_api import MemberApiError
from ian.services.member_cache import MemberCache


TPE = timezone(timedelta(hours=8))
FUTURE_VALID_DATE = datetime(2099, 1, 1, tzinfo=TPE).isoformat()
PAST_VALID_DATE = datetime(2000, 1, 1, tzinfo=TPE).isoformat()


def _member(**overrides):
    member = {
        "id": "Alice",
        "email": "alice@example.test",
        "Tier": "",
        "valid_date": FUTURE_VALID_DATE,
        "discord_acc_id": "discord-1",
        "line_acc_id": "line-1",
        "fb_acc_id": "",
        "subscribe": "",
        "personal_prompt": "",
    }
    member.update(overrides)
    return member


@pytest.fixture
def install_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(member_store, "load_member_db", lambda: False)

    def _install(members):
        cache = MemberCache(tmp_path / "member-cache.json", members)
        monkeypatch.setattr(member_store, "_cache", cache)
        return cache

    return _install


def _reject_api_call(*_args):
    raise AssertionError("member API should not be called")


@pytest.mark.parametrize(
    ("members", "email", "platform", "account_id", "expected_message"),
    [
        pytest.param(
            [_member(discord_acc_id="")],
            "alice@example.test",
            "Unknown",
            "account-1",
            "不支援的平台: Unknown",
            id="unsupported-platform",
        ),
        pytest.param(
            [_member(discord_acc_id="")],
            "alice@example.test",
            "Discord",
            "",
            "無法取得您的帳號 ID",
            id="missing-account-id",
        ),
        pytest.param(
            [_member(discord_acc_id="")],
            "",
            "Discord",
            "discord-new",
            "找不到此 Email",
            id="missing-email",
        ),
        pytest.param(
            [_member()],
            "alice@example.test",
            "Discord",
            "discord-new",
            "帳號已綁定，無法更換綁定",
            id="email-account-conflict",
        ),
        pytest.param(
            [
                _member(discord_acc_id=""),
                _member(
                    id="Bob",
                    email="bob@example.test",
                    discord_acc_id="discord-new",
                    line_acc_id="line-2",
                ),
            ],
            "alice@example.test",
            "Discord",
            "discord-new",
            "帳號已綁定身分",
            id="account-email-conflict",
        ),
        pytest.param(
            [_member(discord_acc_id="", valid_date=PAST_VALID_DATE)],
            "alice@example.test",
            "Discord",
            "discord-new",
            "資格已過期",
            id="expired-member",
        ),
    ],
)
def test_bind_email_rejects_invalid_or_conflicting_requests(
    monkeypatch,
    install_cache,
    members,
    email,
    platform,
    account_id,
    expected_message,
):
    install_cache(members)
    monkeypatch.setattr(member_store, "update_member_fields", _reject_api_call)

    result = member_store.bind_email(email, platform, account_id)

    assert result["success"] is False
    assert expected_message in result["message"]


def test_bind_email_returns_existing_binding_as_success(monkeypatch, install_cache):
    install_cache([_member()])
    monkeypatch.setattr(member_store, "update_member_fields", _reject_api_call)

    result = member_store.bind_email("alice@example.test", "Discord", "discord-1")

    assert result["success"] is True
    assert "已經綁定" in result["message"]


def test_bind_email_updates_api_and_isolated_cache(monkeypatch, install_cache):
    cache = install_cache([_member(discord_acc_id="")])
    api_calls = []
    monkeypatch.setattr(
        member_store,
        "update_member_fields",
        lambda api_url, api_key, email, fields: api_calls.append((email, fields)),
    )

    result = member_store.bind_email("alice@example.test", "Discord", "discord-new")

    assert result["success"] is True
    assert "綁定成功" in result["message"]
    assert api_calls == [("alice@example.test", {"discord_acc_id": "discord-new"})]
    assert cache.find_by_email("alice@example.test")["discord_acc_id"] == "discord-new"
    assert cache.path.exists()


@pytest.mark.parametrize(
    ("error", "expected_message"),
    [
        pytest.param(MemberApiError("locked"), "API 更新失敗: locked", id="api-error"),
        pytest.param(
            RuntimeError("unavailable"),
            "綁定時發生錯誤: unavailable",
            id="unexpected-error",
        ),
    ],
)
def test_bind_email_reports_api_failures(
    monkeypatch, install_cache, error, expected_message
):
    cache = install_cache([_member(discord_acc_id="")])

    def fail(*_args):
        raise error

    monkeypatch.setattr(member_store, "update_member_fields", fail)

    result = member_store.bind_email("alice@example.test", "Discord", "discord-new")

    assert result == {"success": False, "message": expected_message}
    assert cache.find_by_email("alice@example.test")["discord_acc_id"] == ""


def test_bind_email_continues_when_local_cache_save_fails(
    monkeypatch, install_cache, capsys
):
    cache = install_cache([_member(discord_acc_id="")])
    monkeypatch.setattr(member_store, "update_member_fields", lambda *_args: None)
    monkeypatch.setattr(
        cache,
        "save",
        lambda: (_ for _ in ()).throw(OSError("disk full")),
    )

    result = member_store.bind_email("alice@example.test", "Discord", "discord-new")

    assert result["success"] is True
    assert cache.find_by_email("alice@example.test")["discord_acc_id"] == "discord-new"
    entry = json.loads(capsys.readouterr().err)
    assert entry["event"] == "operation_failed"
    assert entry["operation"] == "save_member_cache"
    assert entry["source"] == "bind_email"
    assert entry["error_type"] == "OSError"
    assert "disk full" not in json.dumps(entry)


@pytest.mark.parametrize(
    (
        "member",
        "platform",
        "account_id",
        "subscribe",
        "expected_success",
        "expected_message",
        "expected_update",
    ),
    [
        pytest.param(
            None,
            "Discord",
            "missing",
            "discord",
            False,
            "找不到您的社員資料",
            None,
            id="missing-member",
        ),
        pytest.param(
            _member(valid_date=PAST_VALID_DATE),
            "Discord",
            "discord-1",
            "discord",
            False,
            "社員資格已過期",
            None,
            id="expired-member",
        ),
        pytest.param(
            _member(subscribe="discord"),
            "Discord",
            "discord-1",
            "",
            True,
            "已取消所有通知訂閱",
            ("alice@example.test", {"subscribe": ""}),
            id="unsubscribe-all",
        ),
        pytest.param(
            _member(),
            "Discord",
            "discord-1",
            "slack",
            False,
            "不支援的平台: slack",
            None,
            id="invalid-platform",
        ),
        pytest.param(
            _member(discord_acc_id=""),
            "LINE",
            "line-1",
            "discord",
            False,
            "尚未綁定 discord 帳號",
            None,
            id="unbound-discord",
        ),
        pytest.param(
            _member(discord_acc_id="0"),
            "LINE",
            "line-1",
            "discord",
            False,
            "尚未綁定 discord 帳號",
            None,
            id="zero-discord-id",
        ),
        pytest.param(
            _member(),
            "Discord",
            "discord-1",
            " Discord, discord ",
            True,
            "訂閱設定已更新",
            ("alice@example.test", {"subscribe": "discord"}),
            id="success",
        ),
    ],
)
def test_update_subscribe_validates_and_updates_isolated_cache(
    monkeypatch,
    install_cache,
    member,
    platform,
    account_id,
    subscribe,
    expected_success,
    expected_message,
    expected_update,
):
    cache = install_cache([] if member is None else [member])
    api_calls = []
    monkeypatch.setattr(
        member_store,
        "update_member_fields",
        lambda api_url, api_key, email, fields: api_calls.append((email, fields)),
    )

    result = member_store.update_subscribe(platform, account_id, subscribe)

    assert result["success"] is expected_success
    assert expected_message in result["message"]
    assert api_calls == ([] if expected_update is None else [expected_update])
    if expected_update is not None:
        assert (
            cache.find_by_email("alice@example.test")["subscribe"]
            == expected_update[1]["subscribe"]
        )


def test_update_subscribe_reports_api_failure(monkeypatch, install_cache):
    cache = install_cache([_member()])

    def fail(*_args):
        raise MemberApiError("locked")

    monkeypatch.setattr(member_store, "update_member_fields", fail)

    result = member_store.update_subscribe("Discord", "discord-1", "discord")

    assert result == {"success": False, "message": "API 更新失敗: locked"}
    assert cache.find_by_email("alice@example.test")["subscribe"] == ""


def test_update_subscribe_continues_when_local_cache_save_fails(
    monkeypatch, install_cache, capsys
):
    cache = install_cache([_member()])
    monkeypatch.setattr(member_store, "update_member_fields", lambda *_args: None)
    monkeypatch.setattr(
        cache,
        "save",
        lambda: (_ for _ in ()).throw(OSError("disk full")),
    )

    result = member_store.update_subscribe("Discord", "discord-1", "discord")

    assert result["success"] is True
    assert cache.find_by_email("alice@example.test")["subscribe"] == "discord"
    entry = json.loads(capsys.readouterr().err)
    assert entry["event"] == "operation_failed"
    assert entry["operation"] == "save_member_cache"
    assert entry["source"] == "update_member_field"
    assert entry["error_type"] == "OSError"
    assert "disk full" not in json.dumps(entry)


def test_update_personal_prompt_rejects_missing_member(monkeypatch, install_cache):
    install_cache([])
    monkeypatch.setattr(member_store, "update_member_fields", _reject_api_call)

    result = member_store.update_personal_prompt("Discord", "missing", "concise")

    assert result == {
        "success": False,
        "message": "找不到您的社員資料，無法更新個人備註。",
    }


@pytest.mark.parametrize(
    ("prompt", "expected_value"),
    [
        pytest.param("  concise replies  ", "concise replies", id="trimmed"),
        pytest.param("x" * 101, "x" * 100, id="truncated"),
    ],
)
def test_update_personal_prompt_normalizes_and_saves(
    monkeypatch, install_cache, prompt, expected_value
):
    cache = install_cache([_member()])
    api_calls = []
    monkeypatch.setattr(
        member_store,
        "update_member_fields",
        lambda api_url, api_key, email, fields: api_calls.append((email, fields)),
    )

    result = member_store.update_personal_prompt("Discord", "discord-1", prompt)

    assert result == {"success": True, "message": "已更新使用者個性備註。"}
    assert api_calls == [("alice@example.test", {"personal_prompt": expected_value})]
    assert (
        cache.find_by_email("alice@example.test")["personal_prompt"] == expected_value
    )


def test_update_personal_prompt_reports_api_failure(monkeypatch, install_cache):
    cache = install_cache([_member()])

    def fail(*_args):
        raise MemberApiError("locked")

    monkeypatch.setattr(member_store, "update_member_fields", fail)

    result = member_store.update_personal_prompt(
        "Discord", "discord-1", "concise replies"
    )

    assert result == {"success": False, "message": "API 更新失敗: locked"}
    assert cache.find_by_email("alice@example.test")["personal_prompt"] == ""
