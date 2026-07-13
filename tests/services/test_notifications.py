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
from types import SimpleNamespace

import pytest

from ian.services import notifications


def _event(**overrides):
    event = {
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
        "slides": "https://slides.example",
    }
    event.update(overrides)
    return event


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        pytest.param("技術部部員", True, id="department-member"),
        pytest.param("社長", True, id="president"),
        pytest.param("一般社員", False, id="regular-member"),
        pytest.param("", False, id="empty-role"),
    ],
)
def test_is_staff_role_matches_staff_keywords(role, expected):
    assert notifications.is_staff_role(role) is expected


@pytest.mark.parametrize(
    ("delivery_results", "expected"),
    [
        pytest.param([], (0, 0), id="no-recipients"),
        pytest.param([True, True], (2, 0), id="all-success"),
        pytest.param([True, False, False], (1, 2), id="mixed-results"),
    ],
)
def test_send_notification_to_members_aggregates_delivery_results(
    monkeypatch, delivery_results, expected
):
    bound = [
        {"discord_id": f"discord-{index}"}
        for index, _result in enumerate(delivery_results)
    ]
    dm_calls = []
    sleep_calls = []
    results = iter(delivery_results)

    monkeypatch.setattr(notifications, "get_valid_bound_members", lambda _members: bound)
    monkeypatch.setattr(
        notifications,
        "send_discord_dm",
        lambda discord_id, message: dm_calls.append((discord_id, message))
        or next(results),
    )
    monkeypatch.setattr(notifications.time, "sleep", sleep_calls.append)

    result = notifications.send_notification_to_members("Notice", [{"raw": "member"}])

    discord_ok, discord_fail = expected
    assert result == {
        "total_members": len(bound),
        "discord_ok": discord_ok,
        "discord_fail": discord_fail,
    }
    assert dm_calls == [
        (f"discord-{index}", "Notice") for index in range(len(delivery_results))
    ]
    assert sleep_calls == [0.5] * len(delivery_results)


@pytest.mark.parametrize(
    ("create_status", "send_status", "expected", "expected_stage"),
    [
        pytest.param(500, None, False, "create_channel", id="create-channel-failure"),
        pytest.param(200, 500, False, "send_message", id="send-message-failure"),
        pytest.param(200, 200, True, "send_message", id="success"),
    ],
)
def test_send_discord_dm_emits_redacted_delivery_result(
    monkeypatch,
    capsys,
    create_status,
    send_status,
    expected,
    expected_stage,
):
    send_calls = []
    monkeypatch.setattr(
        notifications.discord_api,
        "create_dm_channel",
        lambda _user_id: SimpleNamespace(
            status_code=create_status,
            text="private create response",
            json=lambda: {"id": "dm-channel-1"},
        ),
    )
    monkeypatch.setattr(
        notifications.discord_api,
        "send_channel_message",
        lambda channel_id, message: send_calls.append((channel_id, message))
        or SimpleNamespace(status_code=send_status, text="private send response"),
    )

    result = notifications.send_discord_dm("user-1", "private message")

    assert result is expected
    assert send_calls == (
        [] if send_status is None else [("dm-channel-1", "private message")]
    )
    log_entry = json.loads(capsys.readouterr().err)
    assert log_entry["status"] == ("success" if expected else "failure")
    assert log_entry["stage"] == expected_stage
    serialized = json.dumps(log_entry)
    for sensitive in (
        "user-1",
        "dm-channel-1",
        "private message",
        "private create response",
        "private send response",
    ):
        assert sensitive not in serialized


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        pytest.param(200, True, id="ok"),
        pytest.param(201, True, id="created"),
        pytest.param(400, False, id="bad-request"),
        pytest.param(500, False, id="server-error"),
    ],
)
def test_send_discord_channel_message_handles_response_statuses(
    monkeypatch, capsys, status_code, expected
):
    calls = []
    monkeypatch.setattr(
        notifications.discord_api,
        "send_channel_message",
        lambda channel_id, message: calls.append((channel_id, message))
        or SimpleNamespace(status_code=status_code, text="response body"),
    )

    assert notifications.send_discord_channel_message("channel-1", "Notice") is expected
    assert calls == [("channel-1", "Notice")]
    log_entry = json.loads(capsys.readouterr().err)
    assert log_entry["status"] == ("success" if expected else "failure")
    assert log_entry["http_status"] == status_code
    assert "channel-1" not in json.dumps(log_entry)
    assert "response body" not in json.dumps(log_entry)


def test_send_discord_channel_message_handles_api_exception(monkeypatch, capsys):
    def fail(*_args):
        raise RuntimeError("Discord unavailable")

    monkeypatch.setattr(notifications.discord_api, "send_channel_message", fail)

    assert notifications.send_discord_channel_message("channel-1", "Notice") is False
    log_entry = json.loads(capsys.readouterr().err)
    assert log_entry["level"] == "error"
    assert log_entry["status"] == "error"
    assert log_entry["error_type"] == "RuntimeError"
    assert "Discord unavailable" not in json.dumps(log_entry)


@pytest.mark.parametrize(
    ("token", "channel_id"),
    [
        pytest.param("", "channel-1", id="missing-token"),
        pytest.param("token", "", id="missing-channel"),
        pytest.param("", "", id="missing-token-and-channel"),
    ],
)
def test_send_log_is_noop_when_not_configured(monkeypatch, token, channel_id):
    monkeypatch.setattr(notifications, "DISCORD_BOT_TOKEN", token)
    monkeypatch.setattr(notifications, "LOG_CHANNEL_ID", channel_id)
    monkeypatch.setattr(
        notifications,
        "send_discord_channel_message",
        lambda *_: (_ for _ in ()).throw(AssertionError("Discord should not be called")),
    )

    assert notifications.send_log("log message") is None


def test_send_log_delegates_when_configured(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications, "DISCORD_BOT_TOKEN", "token")
    monkeypatch.setattr(notifications, "LOG_CHANNEL_ID", "log-channel")
    monkeypatch.setattr(
        notifications,
        "send_discord_channel_message",
        lambda channel_id, message: calls.append((channel_id, message)) or True,
    )

    notifications.send_log("log message")

    assert calls == [("log-channel", "log message")]


def test_format_staff_notification_includes_event_details_and_note():
    message = notifications.format_staff_notification(_event(), note="請準時")

    for expected in (
        "=== Demo ===",
        "日期: 2026/03/07 六",
        "時間: 19:00",
        "地點: 新生",
        "講者: 講者",
        "對象: 社員",
        "備註: 線上直播",
        "課程大綱:\n大綱",
        "線上連結: https://meet.example",
        "講義: https://slides.example",
        "--- 附註 ---\n請準時",
    ):
        assert expected in message


def test_format_staff_notification_omits_empty_optional_fields():
    message = notifications.format_staff_notification(
        _event(
            time="",
            venue="",
            speaker="",
            outline="",
            target="",
            livestream="N",
            recording="N",
            online_link="",
            slides="",
        )
    )

    for omitted in (
        "時間:",
        "地點:",
        "講者:",
        "對象:",
        "備註:",
        "課程大綱:",
        "線上連結:",
        "講義:",
        "附註",
    ):
        assert omitted not in message


@pytest.mark.parametrize(
    ("livestream", "recording", "expected"),
    [
        pytest.param("Y", "N", "備註: 線上直播", id="livestream"),
        pytest.param("N", "Y", "備註: 提供錄影", id="recording"),
        pytest.param("Y", "Y", "備註: 線上直播 / 提供錄影", id="both"),
    ],
)
def test_format_staff_notification_combines_flags(livestream, recording, expected):
    message = notifications.format_staff_notification(
        _event(livestream=livestream, recording=recording)
    )

    assert expected in message


def test_format_staff_notification_truncates_long_outline():
    message = notifications.format_staff_notification(_event(outline="x" * 301))

    assert f"課程大綱:\n{'x' * 300}..." in message
    assert "x" * 301 not in message
