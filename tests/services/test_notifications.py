from ian.services.notifications import format_staff_notification, is_staff_role


def test_is_staff_role_matches_staff_keywords():
    assert is_staff_role("技術部部員")
    assert is_staff_role("社長")
    assert not is_staff_role("一般社員")


def test_format_staff_notification_includes_event_and_note():
    message = format_staff_notification(
        {
            "title": "Demo",
            "date": "2026/03/07",
            "weekday": "六",
            "time": "19:00",
            "venue": "新生",
            "speaker": "講者",
            "outline": "大綱",
            "target": "社員",
            "livestream": "Y",
            "recording": "N",
            "online_link": "https://meet.example",
            "slides": "",
        },
        note="請準時",
    )

    assert "Demo" in message
    assert "線上直播" in message
    assert "請準時" in message
