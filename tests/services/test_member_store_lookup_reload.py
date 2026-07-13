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


def test_sync_member_data_logs_started_and_completed_without_member_details(
    monkeypatch, tmp_path, capsys
):
    cache = member_store.MemberCache(tmp_path / "members.json")
    members = [_valid_member()]
    monkeypatch.setattr(member_store, "_cache", cache)
    monkeypatch.setattr(member_store, "fetch_members", lambda *_args: members)

    assert member_store.sync_member_data() is True

    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [entry["event"] for entry in entries] == ["job_started", "job_completed"]
    assert entries[-1]["member_count"] == 1
    assert "alice@example.com" not in json.dumps(entries)
    assert "discord-1" not in json.dumps(entries)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(member_store.MemberApiError("private API detail"), id="api-error"),
        pytest.param(RuntimeError("private runtime detail"), id="unexpected-error"),
    ],
)
def test_sync_member_data_logs_error_type_without_message(monkeypatch, capsys, error):
    def fail(*_args):
        raise error

    monkeypatch.setattr(member_store, "fetch_members", fail)

    assert member_store.sync_member_data() is False

    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert entries[-1]["event"] == "job_failed"
    assert entries[-1]["error_type"] == type(error).__name__
    assert str(error) not in json.dumps(entries)
