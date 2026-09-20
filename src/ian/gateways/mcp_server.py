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
import warnings

from mcp.server.fastmcp import FastMCP

from ian.application.member_notifications import (
    EventNotFoundError,
    StaffPermissionError,
)
from ian.config import (
    DISCORD_LOG_CHANNEL_ID,
    MCP_HOST,
    MCP_PORT,
    STAFF_NOTIFICATION_CHANNEL_ID,
)
from ian.bootstrap import get_application
from ian.domain.time import TZ_TPE
from ian.services import rag
from ian.utils.logging import log_event

warnings.filterwarnings("ignore", message="pkg_resources is deprecated")

mcp = FastMCP(host=MCP_HOST, port=MCP_PORT, stateless_http=True)

application = get_application()
event_service = application.events
member_service = application.members
member_notification_service = application.member_notifications
checkin_service = application.checkins
operational_notifier = application.operational_notifications


def initialize_dependencies() -> None:
    """Initialize external data sources when the MCP server starts."""
    try:
        rag.initialize_rag_system()
    except Exception as e:
        log_event(
            "operation_failed",
            "mcp_server",
            level="error",
            status="error",
            operation="initialize_data_sources",
            error=e,
        )


def _log_mcp_tool_failure(
    operation: str,
    error: Exception,
    *,
    platform: str | None = None,
    account_id: str | None = None,
) -> None:
    log_event(
        "operation_failed",
        "mcp_server",
        level="error",
        platform=platform,
        status="error",
        operation=operation,
        account_id=account_id,
        error=error,
    )


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool(name="event_retriever")
async def event_retriever(
    platform: str = "",
    account_id: str = "",
    query: str = "",
) -> str:
    """Search published Events visible to the caller's membership tier."""
    try:
        tier = await member_service.get_member_tier(platform, account_id)
        log_event(
            "tool_invoked",
            "mcp_server",
            platform=platform,
            status="started",
            operation="event_retriever",
            account_id=account_id,
            viewer_tier=int(tier),
            query_length=len(query),
        )
        events = await event_service.search_events(query, int(tier))
        return event_service.format_events(events) if events else "未找到可查看的活動資訊。"
    except Exception as error:
        _log_mcp_tool_failure("event_retriever", error, platform=platform, account_id=account_id)
        return "活動資料暫時無法取得，請稍後再試。"


@mcp.tool(name="qa_retreviler")
async def search_qa_chunks_by_semantics(query: str, top_k: int = 5) -> str:
    """
    根據使用者的問題意圖，檢索與社團行政事務（如社費、參加資格、活動報名等）相關的 Q&A 條目，才呼叫此工具。
    Args:
        query: 使用者問題
        top_k: 返回最相關的結果數量（預設為5）
    """
    try:
        if not rag.is_initialized():
            return "錯誤：RAG 系統未初始化，請檢查資料檔案是否存在"

        # 執行混合搜尋（FAISS + BM25，CPU 密集操作）
        results = await asyncio.to_thread(rag.hybrid_search, query, top_k, 0.6)

        if not results:
            return "未找到相關資料"

        # 格式化結果
        formatted_results = []
        for i, (doc, score, methods) in enumerate(results, 1):
            content = doc.page_content
            metadata = doc.metadata

            result = f"=== 結果 {i} (相關度: {score:.3f}, 搜尋方法: {methods}) ===\n"
            result += f"內容：{content}\n"
            result += f"來源：{metadata.get('source', 'unknown')}\n"

            if metadata.get("type") == "faq":
                result += "類型：FAQ\n"
                if metadata.get("tags"):
                    result += f"標籤：{', '.join(metadata.get('tags', []))}\n"
            elif metadata.get("type") == "entity":
                result += f"類型：實體資料 ({metadata.get('entity_type', 'unknown')})\n"
            elif metadata.get("type") == "paragraph":
                result += "類型：段落\n"
                result += f"路徑：{metadata.get('path', 'unknown')}\n"
            elif metadata.get("section_title"):
                result += "類型：文檔章節\n"
                result += f"章節：{metadata.get('section_title')}\n"

            formatted_results.append(result)

        return "\n\n".join(formatted_results)

    except Exception as e:
        return f"搜尋過程發生錯誤: {str(e)}"


@mcp.tool(name="notify_staff")
async def notify_staff(
    message: str,
    user_name: str = "",
    platform: str | None = "",
    context: str = "",
) -> str:
    """
    當 agent 認為需要通知幹部時，使用此工具發送通知訊息到幹部 Discord 頻道。

    適用情況：
    - 使用者詢問合作或商業相關事宜
    - 使用者有投訴或反映問題
    - 使用者詢問的問題超出 AI 能力範圍，需要人工處理
    - 任何需要幹部關注或處理的情況

    Args:
        message: 要通知幹部的訊息內容（應包含摘要和重要資訊）
        user_name: 發起詢問的使用者名稱（選填）
        platform: 使用者所在的平台（如 Discord、FB、LINE）（選填）
        context: 對話的相關上下文（選填）
    """
    try:
        # 格式化通知訊息
        from datetime import datetime, timezone, timedelta

        tz_taipei = timezone(timedelta(hours=8))
        timestamp = datetime.now(tz_taipei).strftime("%Y-%m-%d %H:%M:%S")

        notification = f"📢 **幹部通知** `{timestamp}`\n"

        if user_name:
            notification += f"👤 使用者：`{user_name}`"
            if platform:
                notification += f" ({platform})"
            notification += "\n"

        notification += f"📝 **通知內容**：\n{message}\n"

        if context:
            # 限制 context 長度
            context_preview = context[:500] + "..." if len(context) > 500 else context
            notification += f"\n💬 **相關上下文**：\n{context_preview}"

        success = await operational_notifier.send_channel(
            STAFF_NOTIFICATION_CHANNEL_ID,
            notification,
        )

        if success:
            return "✅ 已成功通知幹部，他們會盡快處理您的需求。"
        else:
            return "⚠️ 通知發送失敗，請稍後再試或透過其他管道聯繫幹部。"

    except Exception as e:
        _log_mcp_tool_failure("notify_staff", e, platform=platform)
        return f"⚠️ 通知發送時發生錯誤：{str(e)}"


@mcp.tool(name="generate_checkin_code")
async def generate_checkin_code(
    platform: str, account_id: str, name: str = "", email: str = ""
) -> str:
    """
    產生使用者專屬的活動簽到碼連結。

    若使用者已是社員（系統可透過平台帳號 ID 在資料庫中找到），會自動使用資料庫中的姓名與 Email 產生簽到碼。
    若使用者不是社員或資料庫中查無資料，則需要使用者提供 name 和 email 來產生簽到碼，
    並提醒他們：擁有簽到碼不代表成功報名或有資格入場，請確認是否已成功報名活動（例如檢查 Email 是否收到報名成功信件）。

    Args:
        platform: 使用者所在的平台（Discord、FB、LINE），從系統訊息中取得 Platform
        account_id: 使用者在該平台上的唯一帳號 ID，從系統訊息中取得 Account ID
        name: （非社員時必填）使用者提供的姓名
        email: （非社員時必填）使用者提供的 Email
    """
    try:
        result = await checkin_service.generate(platform, account_id, name, email)
        if result.status == "member":
            return f"已為社員「{result.name}」產生專屬簽到碼連結：\n{result.url}"
        if result.status == "missing_identity":
            return "在資料庫中查無您的社員資料，請提供您的「姓名」和「Email」以產生簽到碼。"
        if result.status == "invalid_email":
            return "請提供有效的 Email 地址（例如：yourname@gmail.com）"
        return (
            f"已為「{result.name}」產生簽到碼連結：\n{result.url}\n\n"
            "提醒您：擁有簽到碼不代表已成功報名或有資格入場，"
            "請確認您是否已成功報名該活動（例如檢查 Email 是否有收到報名成功的確認信件）。"
        )

    except Exception as e:
        _log_mcp_tool_failure(
            "generate_checkin_code",
            e,
            platform=platform,
            account_id=account_id,
        )
        return f"⚠️ 產生簽到碼時發生錯誤：{str(e)}"


@mcp.tool(name="bind_email")
async def bind_email(email: str, platform: str, account_id: str) -> str:
    """
    透過 Email 綁定社員身分。使用者提供 Email 後，系統會比對社員資料庫，
    若找到匹配的社員，就將該平台的帳號 ID 綁定到該社員帳號上。
    綁定成功後，使用者在該平台上就會被識別為社員。

    注意：
    - Email 的 @ 前面部分不區分大小寫
    - 如果使用者提供的 Email 找不到對應社員，可能是當初申請時使用了其他 Email，請建議使用者聯繫幹部協助查詢

    Args:
        email: 使用者提供的 Email 地址（通常是 Gmail）
        platform: 使用者所在的平台（Discord、FB、LINE）
        account_id: 使用者在該平台上的唯一帳號 ID（從系統訊息中取得 Account ID）
    """
    try:
        if not email or "@" not in email:
            return "請提供有效的 Email 地址（例如：yourname@gmail.com）"

        result = await member_service.bind_user_platform(email, platform, account_id)
        return result.message
    except Exception as e:
        _log_mcp_tool_failure(
            "bind_email",
            e,
            platform=platform,
            account_id=account_id,
        )
        return f"⚠️ 綁定時發生錯誤：{str(e)}"


@mcp.tool(name="update_subscribe")
async def update_subscribe(
    platform: str,
    account_id: str,
    subscribe: str | None = None,
) -> str:
    """
    更新社員的課程通知訂閱設定。社員可以選擇在哪些平台接收每日課程提醒通知。
    系統每天 19:00 會自動通知隔日課程給訂閱者。

    注意：
    - 僅能選擇 discord、fb、line 其中一個平台
    - 使用者必須已綁定該平台帳號才能訂閱該平台的通知
    - 傳入 null 表示取消所有訂閱

    Args:
        platform: 使用者所在的平台（Discord、FB、LINE），從系統訊息中取得 Platform
        account_id: 使用者在該平台上的唯一帳號 ID，從系統訊息中取得 Account ID
        subscribe: 單一平台（discord、fb、line），null 表示取消訂閱
    """
    try:
        result = await member_service.update_user_subscription(
            platform, account_id, subscribe
        )
        return result.message
    except Exception as e:
        _log_mcp_tool_failure(
            "update_subscribe",
            e,
            platform=platform,
            account_id=account_id,
        )
        return f"⚠️ 更新訂閱設定時發生錯誤：{str(e)}"


@mcp.tool(name="update_personal_prompt")
async def update_personal_prompt(
    platform: str, account_id: str, personal_prompt: str
) -> str:
    """
    記錄使用者的溝通風格、興趣領域或互動偏好。這些資訊會在未來的對話中幫助 Agent 調整回應方式。

    注意：
    - 最長 100 字，超過會自動截斷
    - 應整合既有記錄，而非單純覆蓋
    - 不需要每次對話都更新，有新的觀察才更新
    - 只記錄個性與偏好（如溝通風格、興趣領域），不記錄操作事件（如綁定、訂閱）或系統已有的資訊（如姓名、角色）

    Args:
        platform: 使用者所在的平台（Discord、FB、LINE），從系統訊息中取得 Platform
        account_id: 使用者在該平台上的唯一帳號 ID，從系統訊息中取得 Account ID
        personal_prompt: 使用者溝通風格、興趣與偏好的簡短描述（最多 100 字）
    """
    try:
        result = await member_service.update_personal_prompt(
            platform, account_id, personal_prompt
        )
        return result.message
    except Exception as e:
        _log_mcp_tool_failure(
            "update_personal_prompt",
            e,
            platform=platform,
            account_id=account_id,
        )
        return f"⚠️ 更新個性備註時發生錯誤：{str(e)}"


@mcp.tool(name="notify_members")
async def notify_members(
    platform: str,
    account_id: str,
    event_id: int | None = None,
    note: str = "",
    custom_message: str = "",
) -> str:
    """
    幹部專用工具：依有效社員的 subscribe 設定發送 Discord、Facebook、LINE 通知。

    權限限制：系統會依 platform 與 account_id 從 ntuai.dev Users 查詢可信的
    admin／check-in-staff role，不採信呼叫方傳入的角色文字。

    支援兩種通知模式：
    A. 活動通知：提供 event_id，系統自動帶入完整活動資訊
    B. 自訂通知：提供 custom_message，直接發送自訂訊息（不需要選活動）

    使用流程：
    1. 若 event_id 和 custom_message 都未提供，工具會回傳即將舉辦的 3 場活動資訊供選擇
    2. 幹部可選擇一場活動（提供 event_id），或直接提供 custom_message 發送自訂通知
    3. note 為選填備註，活動通知模式下會附加在訊息最後

    Args:
        platform: 使用者所在的平台（Discord、FB、LINE）
        account_id: 使用者在該平台的帳號 ID，系統以此查詢可信的 staff role
        event_id: 要通知的活動 ID，留空則列出即將舉辦的活動
        note: 幹部附註訊息（選填），活動通知時附加在訊息最後
        custom_message: 自訂通知訊息（選填），若提供則直接發送此訊息，不需選擇活動
    """
    try:
        if event_id is not None:
            result = await member_notification_service.notify_event(
                platform,
                account_id,
                event_id,
                note,
            )
            delivery = result.delivery
            return (
                f"通知已發送完成！\n\n"
                f"活動: {result.event.title} (ID: {result.event.id})\n"
                f"通知對象: {delivery.total_members} 位符合活動資格的有效社員\n"
                f"Discord: {delivery.discord_ok} 成功, {delivery.discord_fail} 失敗\n"
                f"Facebook: {delivery.fb_ok} 成功, {delivery.fb_fail} 失敗\n"
                f"LINE: {delivery.line_ok} 成功, {delivery.line_fail} 失敗"
            )

        if custom_message and custom_message.strip():
            log_event(
                "job_started",
                "mcp_server",
                status="started",
                job="notify_members",
                notification_type="custom",
            )
            delivery = await member_notification_service.notify_custom(
                platform,
                account_id,
                custom_message,
            )
            await operational_notifier.send_channel(
                DISCORD_LOG_CHANNEL_ID,
                f"```\n[STAFF NOTIFY] Custom message\n"
                f"Discord: {delivery.discord_ok}/{delivery.discord_ok + delivery.discord_fail}\n"
                f"Facebook: {delivery.fb_ok}/{delivery.fb_ok + delivery.fb_fail}\n"
                f"LINE: {delivery.line_ok}/{delivery.line_ok + delivery.line_fail}\n```",
            )
            log_event(
                "job_completed",
                "mcp_server",
                status=delivery.status,
                job="notify_members",
                notification_type="custom",
                recipient_count=delivery.total_members,
                sent_count=delivery.sent_count,
                failed_count=delivery.failed_count,
            )
            return (
                f"自訂通知已發送完成！\n\n"
                f"通知對象: {delivery.total_members} 位已綁定帳號的有效社員\n"
                f"Discord: {delivery.discord_ok} 成功, {delivery.discord_fail} 失敗\n"
                f"Facebook: {delivery.fb_ok} 成功, {delivery.fb_fail} 失敗\n"
                f"LINE: {delivery.line_ok} 成功, {delivery.line_fail} 失敗"
            )

        upcoming = await member_notification_service.list_upcoming(
            platform,
            account_id,
            limit=3,
        )
    except StaffPermissionError:
        return "此功能僅限已驗證的幹部使用。如果您是幹部但尚未綁定帳號，請先透過 Email 綁定身分。"
    except EventNotFoundError:
        return f"找不到 ID 為 {event_id} 的活動。"
    except Exception as error:
        _log_mcp_tool_failure(
            "notify_members",
            error,
            platform=platform,
            account_id=account_id,
        )
        return "社員通知服務暫時無法使用，請稍後再試。"

    if not upcoming:
        return "目前沒有即將舉辦的活動。你也可以直接提供自訂訊息來通知社員。"

    lines = ["以下是即將舉辦的活動，請選擇要通知社員的活動：\n"]
    for event in upcoming:
        local_start = event.startDate.astimezone(TZ_TPE)
        details = [f"ID {event.id}: {event.title}", f"日期: {local_start:%Y-%m-%d %H:%M}"]
        if event.location:
            details.append(f"地點: {event.location}")
        lines.append("\n".join(details))

    lines.append("\n請提供活動 ID，或直接提供自訂訊息來通知社員。")
    return "\n\n".join(lines)


def run_mcp_server(
    host: str = "0.0.0.0",
    port: int = 5191,
) -> None:
    initialize_dependencies()

    # Stateless Streamable HTTP avoids the legacy SSE session-writer leak.
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def health_check(request):
        """Health check endpoint."""
        return JSONResponse({"status": "ok"})

    mcp._custom_starlette_routes = [
        Route("/health", health_check, methods=["GET"]),
    ]

    log_event(
        "service_started",
        "mcp_server",
        status="running",
        service="mcp_server",
        transport="streamable_http",
        host=host,
        port=port,
    )

    starlette_app = mcp.streamable_http_app()
    uvicorn.run(starlette_app, host=host, port=port, log_level="info")
