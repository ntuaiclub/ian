from datetime import datetime, timedelta, timezone

from ian.domain.members import (
    get_role_from_tier,
    is_valid_member,
    normalize_email,
    parse_subscribe_platforms,
    platform_field,
)


def test_member_validity_uses_taiwan_time():
    future = datetime.now(timezone(timedelta(hours=8))) + timedelta(days=1)
    past = datetime.now(timezone(timedelta(hours=8))) - timedelta(days=1)

    assert is_valid_member({"valid_date": future.isoformat()})
    assert not is_valid_member({"valid_date": past.isoformat()})
    assert not is_valid_member({"valid_date": ""})


def test_role_and_platform_mapping_match_legacy_values():
    assert get_role_from_tier("STAFF") == "幹部"
    assert get_role_from_tier("VIP") == "VIP 社員"
    assert get_role_from_tier("") == "社員"
    assert platform_field("Discord") == "discord_acc_id"
    assert platform_field("LINE") == "line_acc_id"


def test_normalize_email_lowercases_local_part_only():
    assert normalize_email(" USER.Name@Example.COM ") == "user.name@Example.COM"


def test_parse_subscribe_platforms_trims_lowercases_and_deduplicates():
    assert parse_subscribe_platforms(" Discord, discord,  DISCORD ") == ["discord"]
    assert parse_subscribe_platforms(" ") == []
