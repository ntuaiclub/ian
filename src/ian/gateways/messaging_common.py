import json
import os
import sys
from datetime import datetime, timedelta, timezone

UPLOAD_DIR = "uploads"
CHAT_HISTORY_FILE = os.path.join(UPLOAD_DIR, "chat_history.json")


def eprint(*args, **kwargs):
    """Print to stderr."""
    print(*args, file=sys.stderr, **kwargs)


def get_current_time():
    """回傳台灣時區 (UTC+8) 的時間資訊 dict。"""
    now = datetime.now(timezone(timedelta(hours=8)))
    return {
        "nowdatetime": now.strftime("%Y/%m/%d %H:%M:%S"),
        "nowday": now.strftime("%A"),
        "timestamp": now.timestamp(),
    }


def save_chat_history(sender_id, user_name, user_message, bot_response, platform="FB"):
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    history = []
    if os.path.exists(CHAT_HISTORY_FILE):
        with open(CHAT_HISTORY_FILE, "r", encoding="utf-8") as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []

    time_data = get_current_time()
    history.append(
        {
            "timestamp": time_data["nowdatetime"],
            "platform": platform,
            "sender_id": sender_id,
            "user_name": user_name,
            "user_message": user_message,
            "bot_response": bot_response,
        }
    )

    with open(CHAT_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
