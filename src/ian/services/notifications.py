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

import time

import requests

from ian.config import (
    DISCORD_BOT_TOKEN,
    DISCORD_LOG_CHANNEL_ID,
    LINE_CHANNEL_ACCESS_TOKEN,
    PAGE_ACCESS_TOKEN,
)
from ian.domain.members import Platform
from ian.services import discord_api
from ian.services.member_service import ReminderRecipient
from ian.utils.logging import log_event


LOG_CHANNEL_ID = DISCORD_LOG_CHANNEL_ID
STAFF_ROLE_KEYWORDS = ("社長", "部長", "部員")


def send_discord_dm(user_id: str, text: str) -> bool:
    response = discord_api.create_dm_channel(user_id)
    if response.status_code != 200:
        log_event(
            "discord_dm_delivery",
            "notifications",
            level="warning",
            platform="Discord",
            status="failure",
            stage="create_channel",
            user_id=user_id,
            http_status=response.status_code,
        )
        return False

    dm_channel_id = response.json()["id"]
    message_response = discord_api.send_channel_message(dm_channel_id, text)
    if message_response.status_code != 200:
        log_event(
            "discord_dm_delivery",
            "notifications",
            level="warning",
            platform="Discord",
            status="failure",
            stage="send_message",
            user_id=user_id,
            channel_id=dm_channel_id,
            http_status=message_response.status_code,
        )
        return False
    log_event(
        "discord_dm_delivery",
        "notifications",
        platform="Discord",
        status="success",
        stage="send_message",
        user_id=user_id,
        channel_id=dm_channel_id,
        http_status=message_response.status_code,
    )
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
            log_event(
                "discord_channel_message",
                "notifications",
                platform="Discord",
                status="success",
                channel_id=channel_id,
                http_status=response.status_code,
            )
            return True
        log_event(
            "discord_channel_message",
            "notifications",
            level="warning",
            platform="Discord",
            status="failure",
            channel_id=channel_id,
            http_status=response.status_code,
        )
        return False
    except Exception as e:
        log_event(
            "discord_channel_message",
            "notifications",
            level="error",
            platform="Discord",
            status="error",
            channel_id=channel_id,
            error=e,
        )
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


def send_facebook_message(account_id: str, text: str) -> bool:
    if not PAGE_ACCESS_TOKEN:
        return False
    try:
        response = requests.post(
            "https://graph.facebook.com/v18.0/me/messages",
            params={"access_token": PAGE_ACCESS_TOKEN},
            json={"recipient": {"id": account_id}, "message": {"text": text}},
            timeout=10,
        )
        success = response.status_code in (200, 201)
    except requests.RequestException as error:
        log_event(
            "facebook_message_delivery",
            "notifications",
            level="error",
            platform="Facebook",
            status="error",
            account_id=account_id,
            error=error,
        )
        return False

    log_event(
        "facebook_message_delivery",
        "notifications",
        level="info" if success else "warning",
        platform="Facebook",
        status="success" if success else "failure",
        account_id=account_id,
        http_status=response.status_code,
    )
    return success


def send_line_message(account_id: str, text: str) -> bool:
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return False
    try:
        response = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json={"to": account_id, "messages": [{"type": "text", "text": text}]},
            timeout=10,
        )
        success = response.status_code in (200, 201)
    except requests.RequestException as error:
        log_event(
            "line_message_delivery",
            "notifications",
            level="error",
            platform="LINE",
            status="error",
            account_id=account_id,
            error=error,
        )
        return False

    log_event(
        "line_message_delivery",
        "notifications",
        level="info" if success else "warning",
        platform="LINE",
        status="success" if success else "failure",
        account_id=account_id,
        http_status=response.status_code,
    )
    return success


def send_notification(recipient: ReminderRecipient, message: str) -> bool:
    senders = {
        Platform.DISCORD: send_discord_dm,
        Platform.FB: send_facebook_message,
        Platform.LINE: send_line_message,
    }
    return senders[recipient.platform](recipient.account_id, message)


def empty_delivery_result(recipients: list[ReminderRecipient]) -> dict[str, int]:
    return {
        "total_members": len({recipient.user_id for recipient in recipients}),
        "total_recipients": len(recipients),
        "discord_ok": 0,
        "discord_fail": 0,
        "fb_ok": 0,
        "fb_fail": 0,
        "line_ok": 0,
        "line_fail": 0,
    }


def send_notification_to_members(
    message: str,
    recipients: list[ReminderRecipient],
) -> dict[str, int]:
    result = empty_delivery_result(recipients)
    for recipient in recipients:
        success = send_notification(recipient, message)
        result[f"{recipient.platform.value}_{'ok' if success else 'fail'}"] += 1
        time.sleep(0.5)
    return result
