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

import asyncio
import json
from types import SimpleNamespace

import pytest

from ian.domain.events import Event
from ian.domain.members import MemberTier
from ian.gateways import mcp_server


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    ("channel_id", "resolved_role", "expected"),
    [
        pytest.param("allowed", "非社員", (True, "非社員"), id="allowed-channel"),
        pytest.param("", "VIP 社員", (True, "VIP 社員"), id="valid-member"),
        pytest.param("", "非社員", (False, "非社員"), id="non-member"),
        pytest.param(
            "",
            "非社員（會籍已過期）",
            (False, "非社員（會籍已過期）"),
            id="expired-member",
        ),
    ],
)
def test_check_user_permission_uses_allowed_channels_and_member_role(
    monkeypatch, channel_id, resolved_role, expected
):
    monkeypatch.setattr(mcp_server, "ALLOWED_CHANNELS", {"allowed"})

    async def get_member_role(*_args):
        return resolved_role

    monkeypatch.setattr(mcp_server.member_service, "get_member_role", get_member_role)

    assert (
        _run(mcp_server.check_user_permission("Discord", "account-1", channel_id))
        == expected
    )


@pytest.mark.parametrize(
    ("member", "name", "email", "expected_parts"),
    [
        pytest.param(
            {"name": "王 小明", "email": "member+test@example.test"},
            "ignored",
            "ignored@example.test",
            (
                "已為社員「王 小明」",
                "name=%E7%8E%8B%20%E5%B0%8F%E6%98%8E",
                "id=member%2Btest%40example.test",
            ),
            id="bound-member",
        ),
        pytest.param(
            None,
            "",
            "",
            ("請提供您的「姓名」和「Email」",),
            id="missing-non-member-info",
        ),
        pytest.param(
            None, "Visitor", "invalid", ("請提供有效的 Email",), id="invalid-email"
        ),
        pytest.param(
            None,
            "Guest User",
            "guest+event@example.test",
            (
                "已為「Guest User」",
                "name=Guest%20User",
                "id=guest%2Bevent%40example.test",
                "不代表已成功報名",
            ),
            id="non-member-link",
        ),
    ],
)
def test_generate_checkin_code_handles_member_and_guest_flows(
    monkeypatch, member, name, email, expected_parts
):
    async def find_member(*_args):
        return SimpleNamespace(**member) if member else None

    monkeypatch.setattr(mcp_server.member_service, "find_user_by_platform", find_member)

    result = _run(mcp_server.generate_checkin_code("Discord", "account-1", name, email))

    assert all(part in result for part in expected_parts)


@pytest.mark.parametrize(
    ("tool_name", "dependency_name", "args", "error_prefix"),
    [
        pytest.param(
            "bind_email",
            "bind_user_platform",
            ("member@example.test", "Discord", "account-1"),
            "⚠️ 綁定時發生錯誤",
            id="bind-email",
        ),
        pytest.param(
            "update_subscribe",
            "update_user_subscription",
            ("Discord", "account-1", "discord"),
            "⚠️ 更新訂閱設定時發生錯誤",
            id="update-subscribe",
        ),
        pytest.param(
            "update_personal_prompt",
            "update_personal_prompt",
            ("Discord", "account-1", "concise"),
            "⚠️ 更新個性備註時發生錯誤",
            id="update-personal-prompt",
        ),
    ],
)
def test_member_tool_wrappers_return_messages_and_handle_exceptions(
    monkeypatch, tool_name, dependency_name, args, error_prefix
):
    events = []
    monkeypatch.setattr(
        mcp_server,
        "log_event",
        lambda event, component, **fields: events.append(
            {"event": event, "component": component, **fields}
        ),
    )
    tool = getattr(mcp_server, tool_name)

    async def success(*_args):
        return SimpleNamespace(message="service message")

    monkeypatch.setattr(mcp_server.member_service, dependency_name, success)
    assert _run(tool(*args)) == "service message"

    async def fail(*_args):
        raise RuntimeError("service unavailable")

    monkeypatch.setattr(mcp_server.member_service, dependency_name, fail)
    assert _run(tool(*args)) == f"{error_prefix}：service unavailable"
    assert events == [
        {
            "event": "operation_failed",
            "component": "mcp_server",
            "level": "error",
            "platform": "Discord",
            "status": "error",
            "operation": tool_name,
            "account_id": "account-1",
            "error": events[0]["error"],
        }
    ]
    assert isinstance(events[0]["error"], RuntimeError)


def test_notify_members_rejects_non_staff_before_loading_data(monkeypatch):
    monkeypatch.setattr(mcp_server.notifications, "is_staff_role", lambda _role: False)

    async def fail(*_args, **_kwargs):
        raise AssertionError("event data should not load")

    monkeypatch.setattr(mcp_server.event_service, "list_upcoming_events", fail)

    result = _run(mcp_server.notify_members("一般社員"))

    assert "此功能僅限幹部使用" in result


def _stub_staff(monkeypatch):
    monkeypatch.setattr(mcp_server.notifications, "is_staff_role", lambda _role: True)


def _event(event_id=42, *, tier=0):
    return Event.model_validate(
        {
            "id": event_id,
            "title": "Agent Evaluation",
            "startDate": "2026-08-01T19:00:00+08:00",
            "endDate": "2026-08-01T21:00:00+08:00",
            "location": "新生",
            "minimumTier": tier,
            "slug": "agent-evaluation",
            "_status": "published",
        }
    )


def test_notify_members_sends_custom_notification(monkeypatch):
    _stub_staff(monkeypatch)
    delivery = {
        "total_members": 2,
        "discord_ok": 1,
        "discord_fail": 1,
        "fb_ok": 0,
        "fb_fail": 0,
        "line_ok": 0,
        "line_fail": 0,
    }
    sent = []
    logs = []

    async def list_recipients():
        return ["member"]

    monkeypatch.setattr(
        mcp_server.member_service, "list_reminder_recipients", list_recipients
    )
    monkeypatch.setattr(
        mcp_server.notifications,
        "send_notification_to_members",
        lambda message, members: sent.append((message, members)) or delivery,
    )
    monkeypatch.setattr(
        mcp_server.notifications,
        "send_discord_channel_message",
        lambda channel, message: logs.append((channel, message)) or True,
    )

    result = _run(mcp_server.notify_members("部員", custom_message="  Custom alert  "))

    assert sent == [("NTUAI 通知\n\nCustom alert", ["member"])]
    assert "通知對象: 2" in result
    assert "Discord: 1 成功, 1 失敗" in result
    assert len(logs) == 1


def test_notify_members_reports_missing_event_without_sending(monkeypatch):
    _stub_staff(monkeypatch)

    async def find_event(_event_id):
        return None

    monkeypatch.setattr(
        mcp_server.event_service,
        "get_published_event_for_staff",
        find_event,
    )
    monkeypatch.setattr(
        mcp_server.notifications,
        "send_notification_to_members",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("notification should not send")
        ),
    )

    result = _run(mcp_server.notify_members("部長", event_id=42))

    assert result == "找不到 ID 為 42 的活動。"


def test_notify_members_sends_formatted_event_notification(monkeypatch):
    _stub_staff(monkeypatch)
    selected_event = _event(tier=2)
    delivery = {
        "total_members": 3,
        "discord_ok": 3,
        "discord_fail": 0,
        "fb_ok": 0,
        "fb_fail": 0,
        "line_ok": 0,
        "line_fail": 0,
    }
    async def find_event(_event_id):
        return selected_event

    monkeypatch.setattr(
        mcp_server.event_service,
        "get_published_event_for_staff",
        find_event,
    )

    async def list_recipients():
        return [
            SimpleNamespace(tier=MemberTier.LECTURE_EXPLORATION),
            SimpleNamespace(tier=MemberTier.HANDS_ON),
        ]

    monkeypatch.setattr(
        mcp_server.member_service, "list_reminder_recipients", list_recipients
    )
    sent = []
    monkeypatch.setattr(
        mcp_server.notifications,
        "send_notification_to_members",
        lambda message, members: sent.append((message, members)) or delivery,
    )
    monkeypatch.setattr(
        mcp_server.notifications, "send_discord_channel_message", lambda *_: True
    )

    result = _run(mcp_server.notify_members("社長", event_id=42, note=" reminder "))

    assert "活動: Agent Evaluation (ID: 42)" in result
    assert "Discord: 3 成功, 0 失敗" in result
    assert len(sent[0][1]) == 1
    assert sent[0][1][0].tier is MemberTier.HANDS_ON
    assert "附註：reminder" in sent[0][0]


def test_notify_members_lists_upcoming_events_with_ids(monkeypatch):
    _stub_staff(monkeypatch)

    async def list_upcoming_events(*_args, **_kwargs):
        return [_event()]

    monkeypatch.setattr(
        mcp_server.event_service,
        "list_upcoming_events",
        list_upcoming_events,
    )

    result = _run(mcp_server.notify_members("部員"))

    assert "ID 42: Agent Evaluation" in result
    assert "日期: 2026-08-01 19:00" in result
    assert "地點: 新生" in result


def test_stdio_entrypoint_emits_structured_log_without_stdout(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(mcp_server, "initialize_dependencies", lambda: None)
    monkeypatch.setattr(
        mcp_server.mcp,
        "run",
        lambda **kwargs: calls.append(kwargs),
    )

    mcp_server.entrypoint(http=False)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert calls == [{"transport": "stdio"}]
    entry = json.loads(captured.err)
    assert entry["event"] == "service_started"
    assert entry["component"] == "mcp_server"
    assert entry["transport"] == "stdio"
