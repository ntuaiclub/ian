from datetime import datetime, timedelta, timezone

import pandas as pd

from ian.domain.reminders import (
    clean_value,
    find_events_on_date,
    format_reminder_message,
    get_valid_bound_members,
    seconds_until_next_run,
)


def test_get_valid_bound_members_filters_expired_and_unsubscribed_members():
    future = datetime.now(timezone(timedelta(hours=8))) + timedelta(days=1)
    past = datetime.now(timezone(timedelta(hours=8))) - timedelta(days=1)
    members = [
        {"valid_date": future.isoformat(), "subscribe": "discord", "discord_acc_id": "123", "name": "A"},
        {"valid_date": past.isoformat(), "subscribe": "discord", "discord_acc_id": "456", "name": "B"},
        {"valid_date": future.isoformat(), "subscribe": "", "discord_acc_id": "789", "name": "C"},
    ]

    assert get_valid_bound_members(members) == [
        {"name": "A", "email": "", "tier": "", "discord_id": "123"}
    ]


def test_find_events_on_date_cleans_empty_values():
    df = pd.DataFrame(
        [
            {"時間": "2026/03/07", "星期": "六", "活動時間": "-", "場地": "無", "社課主題 / 活動名稱": "Demo"},
            {"時間": "2026/03/08", "社課主題 / 活動名稱": "Other"},
        ]
    )

    events = find_events_on_date(df, "2026/03/07")
    assert events[0]["title"] == "Demo"
    assert events[0]["time"] == ""
    assert events[0]["venue"] == ""
    assert clean_value(float("nan")) == ""


def test_format_reminder_message_includes_event_details():
    message = format_reminder_message(
        [
            {
                "date": "2026/03/07",
                "weekday": "六",
                "time": "19:00",
                "venue": "新生",
                "title": "Demo",
                "speaker": "講者",
                "outline": "大綱",
                "target": "社員",
                "livestream": "Y",
                "recording": "N",
                "online_link": "https://meet.example",
                "slides": "",
            }
        ]
    )
    assert "Hi! 明天 NTUAI 有以下活動：" in message
    assert "Demo" in message
    assert "線上直播" in message
    assert "https://meet.example" in message


def test_seconds_until_next_run_returns_next_future_target():
    now = datetime(2026, 3, 7, 20, 0, tzinfo=timezone(timedelta(hours=8)))
    assert seconds_until_next_run(now, hour=19, minute=0) == 23 * 60 * 60
