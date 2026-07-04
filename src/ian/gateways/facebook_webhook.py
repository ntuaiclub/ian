import asyncio
import threading
import time

import pandas as pd
import requests

from ian.config import MEMBER_MAPPING_FILE, PAGE_ACCESS_TOKEN
from ian.gateways.messaging_common import (
    eprint,
    get_current_time,
    save_chat_history,
)
from ian.services.agent_runtime import chat_with_agent, parse_no_response, start_dispatcher
from ian.services.member_store import (
    get_member_name as get_member_name_from_db,
    get_member_role as get_member_role_from_db,
)

MAPPING_FILE_PATH = MEMBER_MAPPING_FILE

PROCESSED_MESSAGES = {}
PROCESSED_MESSAGES_LOCK = threading.Lock()
CACHE_EXPIRATION_SECONDS = 600


def cleanup_processed_messages():
    with PROCESSED_MESSAGES_LOCK:
        current_time = time.time()
        expired_mids = [
            mid
            for mid, timestamp in PROCESSED_MESSAGES.items()
            if current_time - timestamp > CACHE_EXPIRATION_SECONDS
        ]
        for mid in expired_mids:
            del PROCESSED_MESSAGES[mid]


def get_member_mapping(username: str, csv_path: str):
    try:
        df = pd.read_csv(csv_path)
        features = df.columns.to_list()
        account_col = "FB帳號"

        if account_col not in features or "角色" not in features:
            raise ValueError(f"CSV 檔案必須包含 '{account_col}' 和 '角色' 欄位")

        mapping = dict(zip(df[account_col], df["角色"]))
        return mapping.get(username.strip(), "非社員（尚未加入 AI 社）")
    except Exception as e:
        print(f"讀取檔案失敗：{e}")
        return "非社員"


async def send_typing_indicator(recipient_id, action="typing_on"):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    data = {"recipient": {"id": recipient_id}, "sender_action": action}
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, headers=headers, json=data, timeout=3)
        if response.status_code != 200:
            print(f"發送 FB 輸入狀態失敗: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"發送 FB 輸入狀態時連線失敗: {e}")


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


async def process_message_task(sender_id, user_message, mid=None):
    try:
        await send_typing_indicator(sender_id, "typing_on")
        user_name = get_fb_user_profile(sender_id) or get_member_name_from_db("FB", sender_id) or "FB訪客"
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
        bot_response = await chat_with_agent(
            sender_id,
            user_name,
            user_message,
            roles,
            current_time["timestamp"],
            channel_id="NaN",
            platform="FB",
            account_id=account_id,
        )

        await send_typing_indicator(sender_id, "typing_off")

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


def handle_facebook_messages(data):
    cleanup_processed_messages()

    for entry in data.get("entry", []):
        for messaging_event in entry.get("messaging", []):
            message_obj = messaging_event.get("message")

            if message_obj and message_obj.get("text") and not message_obj.get("is_echo"):
                mid = message_obj.get("mid")
                if not mid:
                    continue

                with PROCESSED_MESSAGES_LOCK:
                    if mid in PROCESSED_MESSAGES:
                        print(f"偵測到重複的訊息 ID (mid: {mid})，已略過。")
                        continue
                    PROCESSED_MESSAGES[mid] = time.time()

                sender_id = messaging_event["sender"]["id"]
                user_message = message_obj["text"]

                coro = process_message_task(sender_id, user_message, mid=mid)
                thread = threading.Thread(target=asyncio.run, args=(coro,))
                thread.start()
