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

from ian.application.member_notifications import (
    EventNotFoundError,
    EventNotificationResult,
)
from ian.application.notifications import DeliveryReport
from ian.application.rag import RagSearchResult
from ian.domain.events import Event
from ian.gateways import mcp_server


def _run(coro):
    return asyncio.run(coro)


def test_initialize_dependencies_delegates_to_rag_service(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mcp_server.rag_service,
        "initialize",
        lambda: calls.append(True) or True,
    )

    mcp_server.initialize_dependencies()

    assert calls == [True]


def test_qa_retriever_reports_uninitialized_rag(monkeypatch):
    monkeypatch.setattr(mcp_server.rag_service, "is_initialized", lambda: False)

    result = _run(mcp_server.search_qa_chunks_by_semantics("社課時間"))

    assert result == "錯誤：RAG 系統未初始化，請檢查資料檔案是否存在"


def test_qa_retriever_formats_application_results(monkeypatch):
    monkeypatch.setattr(mcp_server.rag_service, "is_initialized", lambda: True)

    async def search(query, top_k):
        assert (query, top_k) == ("社課時間", 3)
        return [
            RagSearchResult(
                content="問題：社課時間？\n答案：星期四",
                score=0.8,
                methods="BM25+Semantic",
                source="faq",
                content_type="faq",
                tags=("社課", "時間"),
            )
        ]

    monkeypatch.setattr(mcp_server.rag_service, "search", search)

    result = _run(mcp_server.search_qa_chunks_by_semantics("社課時間", top_k=3))

    assert "相關度: 0.800" in result
    assert "搜尋方法: BM25+Semantic" in result
    assert "問題：社課時間？" in result
    assert "來源：faq" in result
    assert "類型：FAQ" in result
    assert "標籤：社課, 時間" in result


def test_mcp_does_not_expose_legacy_checkin_tool():
    tool_names = {tool.name for tool in _run(mcp_server.mcp.list_tools())}

    assert "generate_checkin_code" not in tool_names
    assert {
        "event_retriever",
        "qa_retreviler",
        "notify_staff",
        "notify_members",
        "bind_email",
        "update_subscribe",
        "update_personal_prompt",
    }.issubset(tool_names)


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
    async def reject(*_args, **_kwargs):
        raise mcp_server.StaffPermissionError

    monkeypatch.setattr(
        mcp_server.member_notification_service,
        "list_upcoming",
        reject,
    )

    result = _run(mcp_server.notify_members("Discord", "account-1"))

    assert "此功能僅限已驗證的幹部使用" in result


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
    delivery = DeliveryReport(total_members=2, discord_ok=1, discord_fail=1)
    logs = []

    async def notify_custom(platform, account_id, message):
        assert (platform, account_id) == ("Discord", "account-1")
        assert message == "  Custom alert  "
        return delivery

    monkeypatch.setattr(
        mcp_server.member_notification_service,
        "notify_custom",
        notify_custom,
    )

    async def send_channel(channel, message):
        logs.append((channel, message))
        return True

    monkeypatch.setattr(
        mcp_server.operational_notifier,
        "send_channel",
        send_channel,
    )

    result = _run(
        mcp_server.notify_members(
            "Discord",
            "account-1",
            custom_message="  Custom alert  ",
        )
    )

    assert "通知對象: 2" in result
    assert "Discord: 1 成功, 1 失敗" in result
    assert len(logs) == 1


def test_notify_members_reports_missing_event_without_sending(monkeypatch):
    async def notify_event(*_args, **_kwargs):
        raise EventNotFoundError(42)

    monkeypatch.setattr(
        mcp_server.member_notification_service,
        "notify_event",
        notify_event,
    )

    result = _run(mcp_server.notify_members("Discord", "account-1", event_id=42))

    assert result == "找不到 ID 為 42 的活動。"


def test_notify_members_sends_formatted_event_notification(monkeypatch):
    selected_event = _event(tier=2)
    delivery = DeliveryReport(total_members=1, discord_ok=1)

    async def notify_event(platform, account_id, event_id, note):
        assert (platform, account_id, event_id, note) == (
            "Discord",
            "account-1",
            42,
            " reminder ",
        )
        return EventNotificationResult(selected_event, delivery)

    monkeypatch.setattr(
        mcp_server.member_notification_service,
        "notify_event",
        notify_event,
    )

    result = _run(
        mcp_server.notify_members(
            "Discord",
            "account-1",
            event_id=42,
            note=" reminder ",
        )
    )

    assert "活動: Agent Evaluation (ID: 42)" in result
    assert "Discord: 1 成功, 0 失敗" in result


def test_notify_members_lists_upcoming_events_with_ids(monkeypatch):
    async def list_upcoming(*_args, **_kwargs):
        return [_event()]

    monkeypatch.setattr(
        mcp_server.member_notification_service,
        "list_upcoming",
        list_upcoming,
    )

    result = _run(mcp_server.notify_members("Discord", "account-1"))

    assert "ID 42: Agent Evaluation" in result
    assert "日期: 2026-08-01 19:00" in result
    assert "地點: 新生" in result


def test_mcp_runner_starts_streamable_http_server(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(mcp_server, "initialize_dependencies", lambda: None)
    monkeypatch.setattr(
        mcp_server.mcp,
        "streamable_http_app",
        lambda: "starlette-app",
    )
    import uvicorn

    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda app, **kwargs: calls.append((app, kwargs)),
    )

    mcp_server.run_mcp_server(host="127.0.0.1", port=6000)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert calls == [
        (
            "starlette-app",
            {"host": "127.0.0.1", "port": 6000, "log_level": "info"},
        )
    ]
    entry = json.loads(captured.err)
    assert entry["event"] == "service_started"
    assert entry["component"] == "mcp_server"
    assert entry["transport"] == "streamable_http"
