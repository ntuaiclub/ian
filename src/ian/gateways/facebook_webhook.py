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

import pandas as pd
import requests

from ian.config import MEMBER_MAPPING_FILE, PAGE_ACCESS_TOKEN
from ian.gateways.agent_bridge import run_agent_message_flow
from ian.gateways.messaging_common import (
    get_current_time,
    save_chat_history,
)
from ian.services.member_store import (
    get_member_name as get_member_name_from_db,
    get_member_role as get_member_role_from_db,
)
from ian.utils.logging import elapsed_ms, hash_identifier, log_event

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
        log_event(
            "operation_failed",
            "facebook_webhook",
            level="error",
            platform="Facebook",
            status="error",
            operation="load_member_mapping",
            error=e,
        )
        return "非社員"


async def send_typing_indicator(recipient_id, action="typing_on", correlation_id=None):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    data = {"recipient": {"id": recipient_id}, "sender_action": action}
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, headers=headers, json=data, timeout=3)
        if response.status_code != 200:
            log_event(
                "external_send_failure",
                "facebook_webhook",
                level="warning",
                platform="Facebook",
                status="failure",
                correlation_id=correlation_id,
                recipient_id=recipient_id,
                operation="typing_indicator",
                http_status=response.status_code,
            )
    except requests.exceptions.RequestException as e:
        log_event(
            "external_send_failure",
            "facebook_webhook",
            level="error",
            platform="Facebook",
            status="error",
            correlation_id=correlation_id,
            recipient_id=recipient_id,
            operation="typing_indicator",
            error=e,
        )


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
            log_event(
                "external_send_failure",
                "facebook_webhook",
                level="warning",
                platform="Facebook",
                status="failure",
                sender_id=sender_id,
                operation="get_user_profile",
                http_status=response.status_code,
            )
            return None
    except requests.exceptions.RequestException as e:
        log_event(
            "external_send_failure",
            "facebook_webhook",
            level="error",
            platform="Facebook",
            status="error",
            sender_id=sender_id,
            operation="get_user_profile",
            error=e,
        )
        return None


def send_message(recipient_id, text, correlation_id=None):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code != 200:
            log_event(
                "external_send_failure",
                "facebook_webhook",
                level="warning",
                platform="Facebook",
                status="failure",
                correlation_id=correlation_id,
                recipient_id=recipient_id,
                operation="send_message",
                http_status=response.status_code,
            )
        else:
            log_event(
                "reply_sent",
                "facebook_webhook",
                platform="Facebook",
                status="success",
                correlation_id=correlation_id,
                recipient_id=recipient_id,
            )
    except requests.exceptions.RequestException as e:
        log_event(
            "external_send_failure",
            "facebook_webhook",
            level="error",
            platform="Facebook",
            status="error",
            correlation_id=correlation_id,
            recipient_id=recipient_id,
            operation="send_message",
            error=e,
        )


def send_reaction(recipient_id, mid, emoji, correlation_id=None):
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
            log_event(
                "external_send_failure",
                "facebook_webhook",
                level="warning",
                platform="Facebook",
                status="failure",
                correlation_id=correlation_id,
                recipient_id=recipient_id,
                message_id=mid,
                operation="send_reaction",
                http_status=response.status_code,
            )
        else:
            log_event(
                "reply_sent",
                "facebook_webhook",
                platform="Facebook",
                status="success",
                correlation_id=correlation_id,
                recipient_id=recipient_id,
                message_id=mid,
                reply_type="reaction",
            )
    except requests.exceptions.RequestException as e:
        log_event(
            "external_send_failure",
            "facebook_webhook",
            level="error",
            platform="Facebook",
            status="error",
            correlation_id=correlation_id,
            recipient_id=recipient_id,
            message_id=mid,
            operation="send_reaction",
            error=e,
        )


async def process_message_task(sender_id, user_message, mid=None):
    correlation_id = hash_identifier(mid or sender_id)
    started_at = time.monotonic()
    try:
        await send_typing_indicator(sender_id, "typing_on", correlation_id)
        user_name = get_fb_user_profile(sender_id) or get_member_name_from_db("FB", sender_id) or "FB訪客"
        roles = get_member_role_from_db("FB", sender_id)
        account_id = sender_id
        if roles == "非社員":
            csv_role = get_member_mapping(user_name, MAPPING_FILE_PATH)
            if csv_role != "非社員（尚未加入 AI 社）":
                roles = csv_role

        current_time = get_current_time()
        log_event(
            "agent_invoked",
            "facebook_webhook",
            platform="Facebook",
            status="started",
            correlation_id=correlation_id,
            sender_id=sender_id,
            message_length=len(user_message),
        )
        agent_result = await run_agent_message_flow(
            session_id=sender_id,
            user_name=user_name,
            user_message=user_message,
            roles=roles,
            current_time=current_time,
            channel_id="NaN",
            platform="FB",
            account_id=account_id,
        )

        await send_typing_indicator(sender_id, "typing_off", correlation_id)

        if not agent_result.should_reply:
            log_event(
                "no_response",
                "facebook_webhook",
                platform="Facebook",
                status="success",
                duration_ms=elapsed_ms(started_at),
                correlation_id=correlation_id,
                sender_id=sender_id,
                reason="agent_decision",
            )
            if agent_result.reaction_emoji and mid:
                send_reaction(sender_id, mid, agent_result.reaction_emoji, correlation_id)
            return

        send_message(sender_id, agent_result.text, correlation_id)
        save_chat_history(sender_id, user_name, user_message, agent_result.text, "FB")

    except Exception as e:
        log_event(
            "request_failed",
            "facebook_webhook",
            level="error",
            platform="Facebook",
            status="error",
            duration_ms=elapsed_ms(started_at),
            correlation_id=correlation_id,
            sender_id=sender_id,
            error=e,
        )
        send_message(
            sender_id,
            "😰 Ian 目前有點忙碌，請稍後再試。\nIan is currently busy. Please try again later.",
            correlation_id,
        )


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
                        log_event(
                            "request_ignored",
                            "facebook_webhook",
                            platform="Facebook",
                            status="duplicate",
                            correlation_id=hash_identifier(mid),
                            message_id=mid,
                        )
                        continue
                    PROCESSED_MESSAGES[mid] = time.time()

                sender_id = messaging_event["sender"]["id"]
                user_message = message_obj["text"]

                log_event(
                    "request_received",
                    "facebook_webhook",
                    platform="Facebook",
                    status="accepted",
                    correlation_id=hash_identifier(mid),
                    sender_id=sender_id,
                    message_id=mid,
                    message_length=len(user_message),
                )

                coro = process_message_task(sender_id, user_message, mid=mid)
                thread = threading.Thread(target=asyncio.run, args=(coro,))
                thread.start()
