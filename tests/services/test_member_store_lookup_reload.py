from datetime import datetime, timedelta, timezone

from ian.services import member_store


def _valid_member(**overrides):
    member = {
        "id": "Alice",
        "email": "alice@example.com",
        "Tier": "",
        "valid_date": (
            datetime.now(timezone(timedelta(hours=8))) + timedelta(days=1)
        ).isoformat(),
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


def test_get_member_role_uses_reload_helper(monkeypatch):
    calls = []

    def fake_lookup_with_reload(platform, account_id):
        calls.append((platform, account_id))
        return _valid_member(Tier="VIP")

    monkeypatch.setattr(member_store, "_lookup_member_with_reload", fake_lookup_with_reload)

    assert member_store.get_member_role("Discord", "discord-1") == "VIP 社員"
    assert calls == [("Discord", "discord-1")]


def test_update_subscribe_uses_reload_helper(monkeypatch):
    calls = []

    def fake_lookup_with_reload(platform, account_id):
        calls.append((platform, account_id))
        return _valid_member(subscribe="", discord_acc_id="discord-1")

    def fake_update_member_field(email, field, value):
        return {"success": True, "message": "更新成功"}

    monkeypatch.setattr(member_store, "_lookup_member_with_reload", fake_lookup_with_reload)
    monkeypatch.setattr(member_store, "_update_member_field", fake_update_member_field)

    result = member_store.update_subscribe("Discord", "discord-1", "discord")

    assert result["success"] is True
    assert result["message"] == "訂閱設定已更新！您將在以下平台收到每日課程通知：discord"
    assert calls == [("Discord", "discord-1")]
