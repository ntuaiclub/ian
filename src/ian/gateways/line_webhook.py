import asyncio
import threading

import requests
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage

from ian.config import LINE_ALLOWED_GROUPS, LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET
from ian.gateways.messaging_common import (
    get_current_time,
    save_chat_history,
)
from ian.services.agent import (
    add_log,
    chat_with_agent,
    parse_no_response,
    start_dispatcher,
)
from ian.services.member_store import (
    get_member_name as get_member_name_from_db,
    get_member_role as get_member_role_from_db,
)
from ian.utils.console import eprint

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
line_handler = WebhookHandler(LINE_CHANNEL_SECRET)


def get_line_user_profile(user_id):
    """使用 LINE Profile API 取得使用者顯示名稱"""
    try:
        profile = line_bot_api.get_profile(user_id)
        return profile.display_name
    except Exception as e:
        print(f"取得 LINE 使用者資訊失敗: {e}")
        return get_member_name_from_db("LINE", user_id) or f"LINE_{user_id[:8]}"


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
        eprint(f"LINE: 來源 {chat_id} 不在白名單中，忽略")
        return

    actual_question = user_text.strip()

    if not actual_question:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入您的問題！"))
        return

    eprint(f"LINE: [{source_type}:{chat_id}] 收到 {user_id} 的訊息: {actual_question}")

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
        eprint(f"LINE: 載入動畫啟動失敗: {e}")

    coro = process_line_message_task(event.reply_token, user_id, actual_question, chat_id, source_type)
    thread = threading.Thread(target=asyncio.run, args=(coro,))
    thread.start()


async def process_line_message_task(reply_token, user_id, user_message, chat_id, source_type="group"):
    """LINE 訊息背景處理任務。"""
    try:
        user_name = get_line_user_profile(user_id)
        if source_type == "1on1":
            roles = get_member_role_from_db("LINE", user_id)
        else:
            roles = "社員"

        eprint(f"LINE: 處理 {user_name} 的訊息：{user_message}")

        current_time = get_current_time()
        start_dispatcher(user_name, current_time)
        bot_response = await chat_with_agent(
            user_id,
            user_name,
            user_message,
            roles,
            current_time["timestamp"],
            channel_id=str(chat_id),
            platform="LINE",
            account_id=user_id,
        )

        is_no_response, _ = parse_no_response(bot_response)
        if is_no_response:
            eprint("LINE: Agent 決定不回覆此訊息")
            return

        if "已達今日使用上限" in bot_response:
            eprint("LINE: 使用者已達上限，不回覆")
            return

        max_chunk_length = 2000
        text_chunks = []

        if len(bot_response) > max_chunk_length:
            paragraphs = bot_response.split("\n\n")
            current_chunk = ""

            for para in paragraphs:
                if len(current_chunk) + len(para) + 2 <= max_chunk_length:
                    current_chunk += para + "\n\n"
                else:
                    if current_chunk:
                        text_chunks.append(current_chunk.strip())
                    current_chunk = para + "\n\n"

            if current_chunk:
                text_chunks.append(current_chunk.strip())
        else:
            text_chunks = [bot_response]

        max_messages = 5
        line_messages = []
        for chunk in text_chunks[:max_messages]:
            if chunk.strip():
                line_messages.append(TextSendMessage(text=chunk.strip()))

        if line_messages:
            try:
                line_bot_api.reply_message(reply_token, line_messages)
                eprint(f"LINE: reply_message 成功 -> chat_id={chat_id}, 訊息數={len(line_messages)}")
            except Exception as reply_err:
                eprint(f"LINE: reply_message 失敗 -> chat_id={chat_id}, 錯誤: {reply_err}")
                import traceback

                eprint(traceback.format_exc())
                return

        save_chat_history(user_id, user_name, user_message, bot_response, "LINE")
        eprint(f"LINE: 訊息處理完成並已回覆給 {user_name}")

    except Exception as e:
        eprint(f"LINE: 背景訊息處理任務發生錯誤: {e}")
        import traceback

        eprint(traceback.format_exc())
        add_log("ERROR", error=str(e), context=f"LINE message processing for {user_id} in {chat_id}")
