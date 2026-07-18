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

import warnings

import asyncio
from typing import Optional, Tuple

import pandas as pd
from mcp.server.fastmcp import FastMCP

from ian.config import (
    ALLOWED_CHANNELS,
    COURSE_DATA_URL,
    DISCORD_LOG_CHANNEL_ID,
    MCP_HOST,
    MCP_PORT,
    STAFF_NOTIFICATION_CHANNEL_ID,
)
from ian.services import course_catalog
from ian.services import notifications
from ian.services import rag
from ian.services.member_service import member_service
from ian.utils.logging import log_event

warnings.filterwarnings("ignore", message="pkg_resources is deprecated")


# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------
mcp = FastMCP(host=MCP_HOST, port=MCP_PORT, stateless_http=True)

# ---------------------------------------------------------------------------
# Permission control
# ---------------------------------------------------------------------------
NON_MEMBER_PREFIX = "非社員"


async def check_user_permission(
    platform: Optional[str] = None,
    account_id: Optional[str] = None,
    channel_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """Return (has_permission, role) for the user.

    Role is looked up from the bound member DB (NOT from any role string passed
    by the caller / LLM). Permission is granted when:
      - the user is in an allowed channel, OR
      - the user's bound member record is valid (role does not start with 非社員).

    Returns the resolved role string for logging / downstream use.
    """
    role = "非社員"
    if platform and account_id:
        role = await member_service.get_member_role(platform, str(account_id).strip())

    if channel_id and channel_id in ALLOWED_CHANNELS:
        return True, role
    if role and not role.startswith(NON_MEMBER_PREFIX):
        return True, role
    return False, role


def initialize_dependencies() -> None:
    """Initialize external data sources when the MCP server starts."""
    try:
        rag.initialize_rag_system()
        course_catalog.load_course_data_from_url(COURSE_DATA_URL)
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


@mcp.tool(name="course_retreviler")
async def search_course_chunks_by_semantics(
    platform: str = "",
    account_id: str = "",
    query: str = "",
    channel_id: str = "",
) -> str:
    """
    根據使用者的問題意圖，檢索課程大綱或具體活動內容相關的資料（講義、照片、其他附件資料等），僅當問題屬於「課程」或「活動」時，才呼叫此工具。
    若使用者未指定活動內容，請優先回傳近期的活動資料概覽。

    權限控制：
    - 角色由系統自行查詢綁定資料庫判斷，不依賴呼叫方傳入的 role
    - 幹部 / 社員 / VIP 社員：可查看完整課程、活動資料
    - 非社員 / 未綁定者：僅可查看基本課程、活動資訊

    Args:
        platform: 使用者所在平台（Discord、FB、LINE），請從系統訊息中的 Platform 取得
        account_id: 使用者在該平台的帳號 ID，請從系統訊息中的 Account ID 取得
        query: 使用者問題查詢（非必要，需要透過明確的關鍵字來搜尋，像是：課程名稱關鍵字等，否則就留空）。日期請統一使用 YYYY/MM/DD 格式（例如 2026/03/26），查詢日期範圍請用空格分隔兩個日期（例如 2026/03/26 2026/03/30）。短日期如 3/26 也可接受。
        channel_id: 使用者所在的頻道 ID（白名單頻道內具完整權限）
    """
    try:
        # 確保課程資料已載入（會自動使用快取機制）
        # 使用 asyncio.to_thread 避免阻塞 event loop（requests.get / time.sleep 都是同步阻塞）
        await asyncio.to_thread(
            course_catalog.load_course_data_from_url,
            COURSE_DATA_URL,
        )

        # 權限檢查 — 角色一律從綁定 DB 查，不採信 LLM 傳進來的字串
        has_permission, _ = await check_user_permission(
            platform, account_id, channel_id
        )
        log_event(
            "tool_invoked",
            "mcp_server",
            platform=platform,
            status="started",
            operation="course_retriever",
            account_id=account_id,
            channel_id=channel_id,
            has_permission=has_permission,
            query_length=len(query),
        )

        # 檢查是否有查詢條件
        if query and query.strip():
            # 有查詢條件，執行搜尋（包含 jieba 分詞、BM25 等 CPU 密集操作）
            found, result = await asyncio.to_thread(
                course_catalog.search_course_data_by_query,
                query,
                has_permission,
            )
            if found:
                # 找到匹配結果，返回搜尋結果 + 權限提示
                return result + course_catalog.get_permission_notice(has_permission)
            else:
                # 找不到匹配結果，優先回傳近期課程而非全部
                if result.startswith("搜尋課程資料時發生錯誤"):
                    return result
                upcoming = await asyncio.to_thread(
                    course_catalog.get_upcoming_courses, has_permission, 2
                )
                if upcoming:
                    return (
                        f"未找到匹配 '{query}' 的課程資料，以下是近期課程：\n\n{upcoming}"
                        + course_catalog.get_permission_notice(has_permission)
                    )
                else:
                    all_data = await asyncio.to_thread(
                        course_catalog.get_all_course_data, has_permission
                    )
                    return (
                        f"未找到匹配 '{query}' 的課程資料，以下是所有可用的課程資料：\n\n{all_data}"
                        + course_catalog.get_permission_notice(has_permission)
                    )
        else:
            # 沒有查詢條件，返回所有課程資料 + 權限提示
            all_data = await asyncio.to_thread(
                course_catalog.get_all_course_data, has_permission
            )
            return all_data + course_catalog.get_permission_notice(has_permission)

    except Exception as e:
        return f"課程資料檢索錯誤: {str(e)}"


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
    message: str, user_name: str = "", platform: Optional[str] = "", context: str = ""
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

        success = await asyncio.to_thread(
            notifications.send_discord_channel_message,
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
        from urllib.parse import quote

        # 嘗試從資料庫查詢社員資料
        member = await member_service.find_user_by_platform(platform, account_id)

        if member:
            member_name = member.name
            member_email = member.email
            if member_name and member_email:
                url = f"https://watsonshih.github.io/QuickRecord/user.html?name={quote(member_name)}&id={quote(member_email)}"
                return f"已為社員「{member_name}」產生專屬簽到碼連結：\n{url}"

        # 非社員或資料庫查無資料：需要使用者提供 name 和 email
        if not name or not email:
            return "在資料庫中查無您的社員資料，請提供您的「姓名」和「Email」以產生簽到碼。"

        if "@" not in email:
            return "請提供有效的 Email 地址（例如：yourname@gmail.com）"

        url = f"https://watsonshih.github.io/QuickRecord/user.html?name={quote(name)}&id={quote(email)}"
        return (
            f"已為「{name}」產生簽到碼連結：\n{url}\n\n"
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


def _get_upcoming_events(limit: int = 3) -> list[dict]:
    """Return the next N upcoming events from course data."""
    from datetime import datetime, timezone, timedelta

    tz_tpe = timezone(timedelta(hours=8))
    today = datetime.now(tz_tpe).strftime("%Y/%m/%d")

    course_catalog.load_course_data_from_url(COURSE_DATA_URL)
    df = course_catalog.course_data
    if df is None or df.empty:
        return []

    upcoming = []
    for _, row in df.iterrows():
        event_date = str(row.get("時間", "")).strip()
        if not event_date or event_date < today:
            continue
        title = str(row.get("社課主題 / 活動名稱", "")).strip()
        if not title or title.lower() == "nan":
            continue
        weekday = str(row.get("星期", "")).strip() if pd.notna(row.get("星期")) else ""
        event_time = (
            str(row.get("活動時間", "")).strip()
            if pd.notna(row.get("活動時間"))
            else ""
        )
        venue = str(row.get("場地", "")).strip() if pd.notna(row.get("場地")) else ""
        upcoming.append(
            {
                "date": event_date,
                "weekday": weekday,
                "time": event_time,
                "venue": venue,
                "title": title,
            }
        )

    upcoming.sort(key=lambda e: e["date"])
    return upcoming[:limit]


def _find_event_by_date(target_date: str) -> dict | None:
    """Find a single event by exact date (YYYY/MM/DD)."""
    course_catalog.load_course_data_from_url(COURSE_DATA_URL)
    df = course_catalog.course_data
    if df is None or df.empty:
        return None

    for _, row in df.iterrows():
        event_date = str(row.get("時間", "")).strip()
        if event_date == target_date:

            def _c(val):
                s = str(val).strip() if pd.notna(val) else ""
                return "" if s.lower() in ("nan", "-", "無") else s

            return {
                "date": event_date,
                "weekday": _c(row.get("星期")),
                "time": _c(row.get("活動時間")),
                "venue": _c(row.get("場地")),
                "title": _c(row.get("社課主題 / 活動名稱")),
                "speaker": _c(row.get("講者")),
                "outline": _c(row.get("課程大綱")),
                "target": _c(row.get("課程對象")),
                "livestream": _c(row.get("是否直播")),
                "recording": _c(row.get("是否錄影")),
                "online_link": _c(row.get("線上連結")),
                "slides": _c(row.get("課程講義")),
            }
    return None


@mcp.tool(name="notify_members")
async def notify_members(
    role: str, event_date: str = "", note: str = "", custom_message: str = ""
) -> str:
    """
    幹部專用工具：依有效社員的 subscribe 設定發送 Discord、Facebook、LINE 通知。

    權限限制：僅限角色包含「社長」、「部長」、「部員」等幹部身分的使用者使用。
    系統會以硬邏輯檢查角色字串，非幹部無法使用此功能。

    支援兩種通知模式：
    A. 活動通知：提供 event_date，系統自動帶入完整活動資訊
    B. 自訂通知：提供 custom_message，直接發送自訂訊息（不需要選活動）

    使用流程：
    1. 若 event_date 和 custom_message 都未提供，工具會回傳即將舉辦的 3 場活動資訊供選擇
    2. 幹部可選擇一場活動（提供 event_date），或直接提供 custom_message 發送自訂通知
    3. note 為選填備註，活動通知模式下會附加在訊息最後

    Args:
        role: 使用者的角色（系統自動帶入，用於權限檢查）
        event_date: 要通知的活動日期（格式：YYYY/MM/DD），留空則列出即將舉辦的活動
        note: 幹部附註訊息（選填），活動通知時附加在訊息最後
        custom_message: 自訂通知訊息（選填），若提供則直接發送此訊息，不需選擇活動
    """
    # Hard check: must be staff
    if not notifications.is_staff_role(role):
        return "此功能僅限幹部使用（角色需包含社長、部長或部員）。如果您是幹部但尚未綁定帳號，請先透過 Email 綁定身分。"

    # Mode A: custom message (no event needed)
    if custom_message and custom_message.strip():
        message = f"NTUAI 通知\n\n{custom_message.strip()}"
        log_event(
            "job_started",
            "mcp_server",
            status="started",
            job="notify_members",
            notification_type="custom",
        )

        recipients = await member_service.list_reminder_recipients()
        result = await asyncio.to_thread(
            notifications.send_notification_to_members, message, recipients
        )

        summary = (
            f"自訂通知已發送完成！\n\n"
            f"通知對象: {result['total_members']} 位已綁定帳號的有效社員\n"
            f"Discord: {result['discord_ok']} 成功, {result['discord_fail']} 失敗\n"
            f"Facebook: {result['fb_ok']} 成功, {result['fb_fail']} 失敗\n"
            f"LINE: {result['line_ok']} 成功, {result['line_fail']} 失敗"
        )

        await asyncio.to_thread(
            notifications.send_discord_channel_message,
            DISCORD_LOG_CHANNEL_ID,
            f"```\n[STAFF NOTIFY] Custom message\n"
            f"Discord: {result['discord_ok']}/{result['discord_ok'] + result['discord_fail']}\n"
            f"Facebook: {result['fb_ok']}/{result['fb_ok'] + result['fb_fail']}\n"
            f"LINE: {result['line_ok']}/{result['line_ok'] + result['line_fail']}\n```",
        )
        failure_count = result["discord_fail"] + result["fb_fail"] + result["line_fail"]
        sent_count = result["discord_ok"] + result["fb_ok"] + result["line_ok"]
        log_event(
            "job_completed",
            "mcp_server",
            status="success" if failure_count == 0 else "partial_failure",
            job="notify_members",
            notification_type="custom",
            recipient_count=result["total_members"],
            sent_count=sent_count,
            failed_count=failure_count,
        )
        return summary

    # Mode B: event notification
    if event_date and event_date.strip():
        event_date = event_date.strip()
        event = _find_event_by_date(event_date)
        if not event:
            return f"找不到日期為 {event_date} 的活動，請確認日期格式為 YYYY/MM/DD。"

        message = notifications.format_staff_notification(
            event, note=note.strip() if note else ""
        )
        log_event(
            "job_started",
            "mcp_server",
            status="started",
            job="notify_members",
            notification_type="event",
            event_date=event_date,
        )

        recipients = await member_service.list_reminder_recipients()
        result = await asyncio.to_thread(
            notifications.send_notification_to_members, message, recipients
        )

        summary = (
            f"通知已發送完成！\n\n"
            f"活動: {event['title']} ({event_date})\n"
            f"通知對象: {result['total_members']} 位已綁定帳號的有效社員\n"
            f"Discord: {result['discord_ok']} 成功, {result['discord_fail']} 失敗\n"
            f"Facebook: {result['fb_ok']} 成功, {result['fb_fail']} 失敗\n"
            f"LINE: {result['line_ok']} 成功, {result['line_fail']} 失敗"
        )

        await asyncio.to_thread(
            notifications.send_discord_channel_message,
            DISCORD_LOG_CHANNEL_ID,
            f"```\n[STAFF NOTIFY] {event['title']} ({event_date})\n"
            f"Discord: {result['discord_ok']}/{result['discord_ok'] + result['discord_fail']}\n"
            f"Facebook: {result['fb_ok']}/{result['fb_ok'] + result['fb_fail']}\n"
            f"LINE: {result['line_ok']}/{result['line_ok'] + result['line_fail']}\n```",
        )
        failure_count = result["discord_fail"] + result["fb_fail"] + result["line_fail"]
        sent_count = result["discord_ok"] + result["fb_ok"] + result["line_ok"]
        log_event(
            "job_completed",
            "mcp_server",
            status="success" if failure_count == 0 else "partial_failure",
            job="notify_members",
            notification_type="event",
            event_date=event_date,
            recipient_count=result["total_members"],
            sent_count=sent_count,
            failed_count=failure_count,
        )
        return summary

    # Mode C: no event_date and no custom_message — list upcoming events
    upcoming = _get_upcoming_events(3)
    if not upcoming:
        return "目前沒有即將舉辦的活動。你也可以直接提供自訂訊息來通知社員。"

    lines = ["以下是即將舉辦的活動，請選擇要通知社員的活動：\n"]
    for i, ev in enumerate(upcoming, 1):
        parts = [f"{i}. {ev['title']}"]
        parts.append(f"   日期: {ev['date']} {ev['weekday']}")
        if ev["time"]:
            parts.append(f"   時間: {ev['time']}")
        if ev["venue"]:
            parts.append(f"   地點: {ev['venue']}")
        lines.append("\n".join(parts))

    lines.append(
        "\n請告訴我要通知哪一場活動（提供日期即可），也可以直接提供自訂訊息來通知社員。"
    )
    return "\n\n".join(lines)


def entrypoint(http: bool = False, host: str = "0.0.0.0", port: int = 5191):
    initialize_dependencies()

    if http:
        # Use FastMCP's built-in streamable-http transport (stateless mode)
        # This avoids the SSE session leak in mcp/server/sse.py where
        # _read_stream_writers entries accumulate and never get cleaned up.
        import uvicorn
        from starlette.routing import Route
        from starlette.responses import JSONResponse

        async def health_check(request):
            """Health check endpoint"""
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
    else:
        log_event(
            "service_started",
            "mcp_server",
            status="running",
            service="mcp_server",
            transport="stdio",
        )
        mcp.run(transport="stdio")
