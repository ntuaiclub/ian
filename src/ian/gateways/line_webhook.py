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
import threading
import time

import requests
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage

from ian.config import (
    LINE_ALLOWED_GROUPS,
    LINE_CHANNEL_ACCESS_TOKEN,
    LINE_CHANNEL_SECRET,
)
from ian.domain.messages import split_message_chunks
from ian.gateways.agent_bridge import run_agent_message_flow
from ian.gateways.messaging_common import (
    get_current_time,
    save_chat_history,
)
from ian.services.member_service import member_service
from ian.utils.logging import elapsed_ms, hash_identifier, log_event

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
line_handler = WebhookHandler(LINE_CHANNEL_SECRET)


def get_line_user_profile(user_id):
    """使用 LINE Profile API 取得使用者顯示名稱"""
    try:
        profile = line_bot_api.get_profile(user_id)
        return profile.display_name
    except Exception as e:
        log_event(
            "external_send_failure",
            "line_webhook",
            level="error",
            platform="LINE",
            status="error",
            user_id=user_id,
            operation="get_user_profile",
            error=e,
        )
        return None


@line_handler.add(MessageEvent, message=TextMessage)
def handle_line_message(event):
    """處理 LINE 訊息事件。"""
    user_text = event.message.text
    user_id = event.source.user_id

    source_type = "1on1"
    chat_id = None
    if hasattr(event.source, "group_id"):
        chat_id = event.source.group_id
        source_type = "group"
    elif hasattr(event.source, "room_id"):
        chat_id = event.source.room_id
        source_type = "room"
    else:
        chat_id = event.source.user_id

    if source_type != "1on1" and chat_id not in LINE_ALLOWED_GROUPS:
        log_event(
            "request_ignored",
            "line_webhook",
            platform="LINE",
            status="unauthorized",
            correlation_id=hash_identifier(event.reply_token),
            user_id=user_id,
            channel_id=chat_id,
        )
        return

    actual_question = user_text.strip()

    if not actual_question:
        line_bot_api.reply_message(
            event.reply_token, TextSendMessage(text="請輸入您的問題！")
        )
        return

    log_event(
        "request_received",
        "line_webhook",
        platform="LINE",
        status="accepted",
        correlation_id=hash_identifier(event.reply_token),
        user_id=user_id,
        channel_id=chat_id,
        source_type=source_type,
        message_length=len(actual_question),
    )

    try:
        loading_url = "https://api.line.me/v2/bot/chat/loading/start"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        }
        loading_data = {
            "chatId": chat_id,
            "loadingSeconds": 20,
        }
        requests.post(loading_url, headers=headers, json=loading_data, timeout=3)
    except Exception as e:
        log_event(
            "external_send_failure",
            "line_webhook",
            level="error",
            platform="LINE",
            status="error",
            correlation_id=hash_identifier(event.reply_token),
            channel_id=chat_id,
            operation="loading_indicator",
            error=e,
        )

    coro = process_line_message_task(
        event.reply_token, user_id, actual_question, chat_id, source_type
    )
    thread = threading.Thread(target=asyncio.run, args=(coro,))
    thread.start()


async def process_line_message_task(
    reply_token, user_id, user_message, chat_id, source_type="group"
):
    """LINE 訊息背景處理任務。"""
    correlation_id = hash_identifier(reply_token)
    started_at = time.monotonic()
    try:
        member = await member_service.find_user_by_platform("LINE", user_id)
        user_name = (
            get_line_user_profile(user_id)
            or (member.name if member else None)
            or f"LINE_{user_id[:8]}"
        )
        roles = member.member_role() if member else "非社員"

        current_time = get_current_time()
        log_event(
            "agent_invoked",
            "line_webhook",
            platform="LINE",
            status="started",
            correlation_id=correlation_id,
            user_id=user_id,
            channel_id=chat_id,
            message_length=len(user_message),
        )
        agent_result = await run_agent_message_flow(
            session_id=user_id,
            user_name=user_name,
            user_message=user_message,
            roles=roles,
            current_time=current_time,
            channel_id=str(chat_id),
            platform="LINE",
            account_id=user_id,
            member=member,
        )

        if not agent_result.should_reply:
            log_event(
                "no_response",
                "line_webhook",
                platform="LINE",
                status="success",
                duration_ms=elapsed_ms(started_at),
                correlation_id=correlation_id,
                user_id=user_id,
                reason="agent_decision",
            )
            return

        if "已達今日使用上限" in agent_result.text:
            log_event(
                "no_response",
                "line_webhook",
                platform="LINE",
                status="rate_limited",
                duration_ms=elapsed_ms(started_at),
                correlation_id=correlation_id,
                user_id=user_id,
                reason="usage_limit",
            )
            return

        line_messages = []
        for chunk in split_message_chunks(agent_result.text):
            if chunk.strip():
                line_messages.append(TextSendMessage(text=chunk))

        if line_messages:
            try:
                line_bot_api.reply_message(reply_token, line_messages)
                log_event(
                    "reply_sent",
                    "line_webhook",
                    platform="LINE",
                    status="success",
                    duration_ms=elapsed_ms(started_at),
                    correlation_id=correlation_id,
                    user_id=user_id,
                    channel_id=chat_id,
                    message_count=len(line_messages),
                )
            except Exception as reply_err:
                log_event(
                    "external_send_failure",
                    "line_webhook",
                    level="error",
                    platform="LINE",
                    status="error",
                    duration_ms=elapsed_ms(started_at),
                    correlation_id=correlation_id,
                    user_id=user_id,
                    channel_id=chat_id,
                    operation="reply_message",
                    error=reply_err,
                )
                return

        save_chat_history(user_id, user_name, user_message, agent_result.text, "LINE")

    except Exception as e:
        log_event(
            "request_failed",
            "line_webhook",
            level="error",
            platform="LINE",
            status="error",
            duration_ms=elapsed_ms(started_at),
            correlation_id=correlation_id,
            user_id=user_id,
            channel_id=chat_id,
            error=e,
        )
