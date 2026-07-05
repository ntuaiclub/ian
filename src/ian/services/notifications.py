import time

from ian.config import DISCORD_BOT_TOKEN, DISCORD_LOG_CHANNEL_ID
from ian.domain.reminders import get_valid_bound_members
from ian.services import discord_api
from ian.utils.console import eprint


LOG_CHANNEL_ID = DISCORD_LOG_CHANNEL_ID
STAFF_ROLE_KEYWORDS = ("社長", "部長", "部員")


def send_discord_dm(user_id: str, text: str) -> bool:
    response = discord_api.create_dm_channel(user_id)
    if response.status_code != 200:
        eprint(f"  [Discord] Failed to create DM channel for {user_id}: {response.text}")
        return False

    dm_channel_id = response.json()["id"]
    message_response = discord_api.send_channel_message(dm_channel_id, text)
    if message_response.status_code != 200:
        eprint(f"  [Discord] Failed to send message to {user_id}: {message_response.text}")
        return False
    return True


def send_log(message: str):
    if not DISCORD_BOT_TOKEN or not LOG_CHANNEL_ID:
        return
    try:
        send_discord_channel_message(LOG_CHANNEL_ID, message)
    except Exception:
        pass


def send_discord_channel_message(channel_id: str, message: str) -> bool:
    try:
        response = discord_api.send_channel_message(channel_id, message)
        if response.status_code in (200, 201):
            eprint(f"[notify_staff] 成功發送通知到 Discord channel {channel_id}")
            return True
        eprint(f"[notify_staff] 發送失敗: {response.status_code} - {response.text}")
        return False
    except Exception as e:
        eprint(f"[notify_staff] 發送通知時發生錯誤: {e}")
        return False


def is_staff_role(role: str) -> bool:
    if not role:
        return False
    return any(keyword in role for keyword in STAFF_ROLE_KEYWORDS)


def format_staff_notification(event: dict, note: str = "") -> str:
    lines = ["NTUAI 活動通知", "", f"=== {event['title']} ==="]
    lines.append(f"日期: {event['date']} {event['weekday']}")
    if event.get("time"):
        lines.append(f"時間: {event['time']}")
    if event.get("venue"):
        lines.append(f"地點: {event['venue']}")
    if event.get("speaker"):
        lines.append(f"講者: {event['speaker']}")
    if event.get("target"):
        lines.append(f"對象: {event['target']}")

    flags = []
    if event.get("livestream") == "Y":
        flags.append("線上直播")
    if event.get("recording") == "Y":
        flags.append("提供錄影")
    if flags:
        lines.append(f"備註: {' / '.join(flags)}")

    if event.get("outline"):
        outline = event["outline"]
        if len(outline) > 300:
            outline = outline[:300] + "..."
        lines.append(f"\n課程大綱:\n{outline}")

    if event.get("online_link"):
        lines.append(f"\n線上連結: {event['online_link']}")
    if event.get("slides"):
        lines.append(f"講義: {event['slides']}")
    if note:
        lines.append(f"\n--- 附註 ---\n{note}")
    return "\n".join(lines)


def send_notification_to_members(message: str, members: list[dict]) -> dict:
    bound = get_valid_bound_members(members)

    discord_ok, discord_fail = 0, 0
    for member in bound:
        if member["discord_id"]:
            if send_discord_dm(member["discord_id"], message):
                discord_ok += 1
            else:
                discord_fail += 1
            time.sleep(0.5)

    return {
        "total_members": len(bound),
        "discord_ok": discord_ok,
        "discord_fail": discord_fail,
    }
