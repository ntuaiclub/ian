import asyncio
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
from flask import Flask, abort, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

from ian.services.agent_runtime import (
    add_log,
    chat_with_agent,
    parse_no_response,
    start_dispatcher,
)
from ian.services.member_store import (
    get_member_name as get_member_name_from_db,
    get_member_role as get_member_role_from_db,
    init as init_member_db,
)


def eprint(*args, **kwargs):
    """Print to stderr."""
    print(*args, file=sys.stderr, **kwargs)

app = Flask(__name__)

# ====== Facebook Configuration ======
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "")
VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "")
UPLOAD_DIR = "uploads"
CHAT_HISTORY_FILE = os.path.join(UPLOAD_DIR, "chat_history.json")
MAPPING_FILE_PATH = "./data/member_mapping.csv"

# ====== LINE Bot Configuration ======
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
# LINE 群組白名單
LINE_ALLOWED_GROUPS = [
    group_id.strip()
    for group_id in os.environ.get("LINE_ALLOWED_GROUPS", "").split(",")
    if group_id.strip()
]

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
line_handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ====== Message Deduplication Cache ======
PROCESSED_MESSAGES = {}
PROCESSED_MESSAGES_LOCK = threading.Lock()
CACHE_EXPIRATION_SECONDS = 600

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# Initialize member database
try:
    init_member_db()
    eprint("社員資料庫已初始化 (webhook_server)")
except Exception as e:
    eprint(f"社員資料庫初始化失敗: {e}")

def run_async_in_thread(coro):
    """在獨立執行緒中執行協程。"""
    asyncio.run(coro)

# ====== Utility Functions ======
def cleanup_processed_messages():
    with PROCESSED_MESSAGES_LOCK:
        current_time = time.time()
        expired_mids = [
            mid for mid, timestamp in PROCESSED_MESSAGES.items()
            if current_time - timestamp > CACHE_EXPIRATION_SECONDS
        ]
        for mid in expired_mids:
            del PROCESSED_MESSAGES[mid]

def get_current_time():
    """回傳台灣時區 (UTC+8) 的時間資訊 dict。"""
    now = datetime.now(timezone(timedelta(hours=8)))
    return {
        "nowdatetime": now.strftime("%Y/%m/%d %H:%M:%S"),
        "nowday": now.strftime("%A"),
        "timestamp": now.timestamp()
    }

def get_member_mapping(username: str, csv_path: str):
    try:
        df = pd.read_csv(csv_path)
        features = df.columns.to_list()
        account_col = 'FB帳號'

        if account_col not in features or '角色' not in features:
            raise ValueError(f"CSV 檔案必須包含 '{account_col}' 和 '角色' 欄位")

        mapping = dict(zip(df[account_col], df['角色']))
        return mapping.get(username.strip(), "非社員（尚未加入 AI 社）")
    except Exception as e:
        print(f"讀取檔案失敗：{e}")
        return "非社員"

async def send_typing_indicator(recipient_id, action='typing_on'):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    data = {"recipient": {"id": recipient_id}, "sender_action": action}
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, headers=headers, json=data, timeout=3)
        if response.status_code != 200:
            print(f"發送 FB 輸入狀態失敗: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"發送 FB 輸入狀態時連線失敗: {e}")

def save_chat_history(sender_id, user_name, user_message, bot_response, platform="FB"):
    history = []
    if os.path.exists(CHAT_HISTORY_FILE):
        with open(CHAT_HISTORY_FILE, 'r', encoding='utf-8') as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []
    
    time_data = get_current_time()
    history.append({
        "timestamp": time_data["nowdatetime"],
        "platform": platform,
        "sender_id": sender_id,
        "user_name": user_name,
        "user_message": user_message,
        "bot_response": bot_response,
    })
    
    with open(CHAT_HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def get_fb_user_profile(sender_id):
    url = f"https://graph.facebook.com/v18.0/{sender_id}"
    params = {"fields": "first_name,last_name,profile_pic", "access_token": PAGE_ACCESS_TOKEN}
    try:
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            profile = response.json()
            full_name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
            return full_name
        else:
            print(f"取得 FB 使用者資訊失敗: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"連線 Facebook 失敗: {e}")
        return None

def get_line_user_profile(user_id):
    """使用 LINE Profile API 取得使用者顯示名稱"""
    try:
        profile = line_bot_api.get_profile(user_id)
        return profile.display_name
    except Exception as e:
        print(f"取得 LINE 使用者資訊失敗: {e}")
        return get_member_name_from_db("LINE", user_id) or f"LINE_{user_id[:8]}"

def send_message(recipient_id, text):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"傳送 FB 訊息失敗: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"發送 FB 訊息時連線失敗: {e}")

def send_reaction(recipient_id, mid, emoji):
    """Send a reaction emoji to a specific message via FB Graph API."""
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "sender_action": "react",
        "payload": {
            "message_id": mid,
            "reaction": emoji,
        },
    }
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code != 200:
            eprint(f"FB reaction 失敗: {response.text}")
        else:
            eprint(f"FB reaction 成功: {emoji}")
    except requests.exceptions.RequestException as e:
        eprint(f"發送 FB reaction 時連線失敗: {e}")

# ====== Background Message Processing ======
async def process_message_task(sender_id, user_message, mid=None):
    try:
        await send_typing_indicator(sender_id, 'typing_on')
        user_name = get_fb_user_profile(sender_id) or get_member_name_from_db("FB", sender_id) or "FB訪客"
        # Use member DB first (by sender_id), fall back to CSV
        roles = get_member_role_from_db("FB", sender_id)
        account_id = sender_id
        if roles == "非社員":
            csv_role = get_member_mapping(user_name, MAPPING_FILE_PATH)
            if csv_role != "非社員（尚未加入 AI 社）":
                roles = csv_role

        print(f"收到 FB [{roles}]/{user_name} ({sender_id}) 的訊息：{user_message}")
        print(f"傳送給 agent 的身分資訊: {roles}")

        current_time = get_current_time()
        start_dispatcher(user_name, current_time)
        bot_response = await chat_with_agent(sender_id, user_name, user_message, roles, current_time["timestamp"], channel_id="NaN", platform="FB", account_id=account_id)

        await send_typing_indicator(sender_id, 'typing_off')

        is_no_response, reaction_emoji = parse_no_response(bot_response)
        if is_no_response:
            eprint("FB: Agent 決定不回覆此訊息")
            if reaction_emoji and mid:
                send_reaction(sender_id, mid, reaction_emoji)
            return

        send_message(sender_id, bot_response)
        save_chat_history(sender_id, user_name, user_message, bot_response, "FB")
        print(f"FB 訊息處理完成並已回覆給 {user_name}")

    except Exception as e:
        print(f"背景訊息處理任務發生錯誤 (FB, {sender_id}): {e}")
        send_message(sender_id, "😰 Ian 目前有點忙碌，請稍後再試。\nIan is currently busy. Please try again later.")

# ====== Flask 路由 ======
@app.route('/', methods=['GET'])
async def verify():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.challenge"):
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args["hub.challenge"], 200
        return "驗證失敗", 403
    return "Hello World", 200

@app.route('/', methods=['POST'])
async def webhook():
    data = request.get_json()
    try:
        if data.get('object') == 'page':
            handle_facebook_messages(data)
    except Exception as e:
        print(f"Webhook 處理過程中發生未知錯誤: {e}")
    return "ok", 200

# ====== Message Dispatch ======
def handle_facebook_messages(data):
    cleanup_processed_messages()
    
    for entry in data.get('entry', []):
        for messaging_event in entry.get('messaging', []):
            message_obj = messaging_event.get('message')
            
            if message_obj and message_obj.get('text') and not message_obj.get('is_echo'):
                mid = message_obj.get('mid')
                if not mid:
                    continue

                with PROCESSED_MESSAGES_LOCK:
                    if mid in PROCESSED_MESSAGES:
                        print(f"偵測到重複的訊息 ID (mid: {mid})，已略過。")
                        continue
                    PROCESSED_MESSAGES[mid] = time.time()
                
                sender_id = messaging_event['sender']['id']
                user_message = message_obj['text']

                coro = process_message_task(sender_id, user_message, mid=mid)
                thread = threading.Thread(target=run_async_in_thread, args=(coro,))
                thread.start()

# ====== LINE Webhook ======
@app.route('/line/callback', methods=['POST'])
def line_callback():
    """LINE webhook 接收端點。"""
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    
    try:
        line_handler.handle(body, signature)
    except InvalidSignatureError:
        eprint("LINE: Invalid signature")
        abort(400)
    except Exception as e:
        eprint(f"LINE CALLBACK: handler.handle() 發生例外: {e}")
    
    return "OK", 200

@line_handler.add(MessageEvent, message=TextMessage)
def handle_line_message(event):
    """處理 LINE 訊息事件。"""
    user_text = event.message.text
    user_id = event.source.user_id
    
    source_type = "1on1"
    chat_id = None
    if hasattr(event.source, 'group_id'):
        chat_id = event.source.group_id
        source_type = "group"
    elif hasattr(event.source, 'room_id'):
        chat_id = event.source.room_id
        source_type = "room"
    else:
        chat_id = event.source.user_id
    
    if source_type != "1on1" and chat_id not in LINE_ALLOWED_GROUPS:
        eprint(f"LINE: 來源 {chat_id} 不在白名單中，忽略")
        return
    
    actual_question = user_text.strip()
    
    if not actual_question:
        line_bot_api.reply_message(
            event.reply_token, 
            TextSendMessage(text="請輸入您的問題！")
        )
        return
    
    eprint(f"LINE: [{source_type}:{chat_id}] 收到 {user_id} 的訊息: {actual_question}")
    
    # 顯示 LINE 載入動畫
    try:
        loading_url = 'https://api.line.me/v2/bot/chat/loading/start'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
        }
        loading_data = {
            'chatId': chat_id,
            'loadingSeconds': 20
        }
        requests.post(loading_url, headers=headers, json=loading_data, timeout=3)
    except Exception as e:
        eprint(f"LINE: 載入動畫啟動失敗: {e}")
    
    coro = process_line_message_task(event.reply_token, user_id, actual_question, chat_id, source_type)
    thread = threading.Thread(target=run_async_in_thread, args=(coro,))
    thread.start()

async def process_line_message_task(reply_token, user_id, user_message, chat_id, source_type="group"):
    """LINE 訊息背景處理任務。"""
    try:
        user_name = get_line_user_profile(user_id)
        if source_type == "1on1":
            roles = get_member_role_from_db("LINE", user_id)
        else:
            roles = "社員"  # 白名單群組預設為社員

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
        
        # 處理長訊息分段
        MAX_CHUNK_LENGTH = 2000
        text_chunks = []
        
        if len(bot_response) > MAX_CHUNK_LENGTH:
            # 先嘗試用雙換行分段
            paragraphs = bot_response.split("\n\n")
            current_chunk = ""
            
            for para in paragraphs:
                if len(current_chunk) + len(para) + 2 <= MAX_CHUNK_LENGTH:
                    current_chunk += para + "\n\n"
                else:
                    if current_chunk:
                        text_chunks.append(current_chunk.strip())
                    current_chunk = para + "\n\n"
            
            if current_chunk:
                text_chunks.append(current_chunk.strip())
        else:
            text_chunks = [bot_response]
        
        # 產生 LINE 訊息（最多 5 則）
        MAX_MESSAGES = 5
        line_messages = []
        for chunk in text_chunks[:MAX_MESSAGES]:
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

# ====== Status Check ======
@app.route('/status', methods=['GET'])
def status():
    return {
        "status": "running",
        "timestamp": get_current_time()["nowdatetime"],
        "platforms": ["Facebook", "LINE"]
    }, 200

def main():
    print("啟動 Flask 伺服器...")
    app.run(host='0.0.0.0', port=5190, debug=False)


# ====== Main ======
if __name__ == '__main__':
    main()
