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
from typing import Any, Callable

import requests

from ian.config import (
    DISCORD_BOT_TOKEN,
    DISCORD_LOG_CHANNEL_ID,
    LINE_CHANNEL_ACCESS_TOKEN,
    PAGE_ACCESS_TOKEN,
)
from ian.application.members import ReminderRecipient
from ian.domain.members import Platform
from ian.services import discord_api
from ian.utils.logging import log_event


LOG_CHANNEL_ID = DISCORD_LOG_CHANNEL_ID
_DELIVERY_LOCK = threading.Lock()


def _call_with_rate_limit_retry(
    call: Callable[[], Any],
    *,
    max_attempts: int = 3,
) -> Any:
    for attempt in range(max_attempts):
        response = call()
        if response.status_code != 429 or attempt == max_attempts - 1:
            return response
        headers = getattr(response, "headers", {}) or {}
        retry_after = headers.get("Retry-After")
        try:
            delay = float(retry_after) if retry_after is not None else 2**attempt
        except (TypeError, ValueError):
            delay = 2**attempt
        time.sleep(max(delay, 0))
    raise RuntimeError("unreachable retry loop")


def send_discord_dm(user_id: str, text: str) -> bool:
    response = _call_with_rate_limit_retry(
        lambda: discord_api.create_dm_channel(user_id)
    )
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
    message_response = _call_with_rate_limit_retry(
        lambda: discord_api.send_channel_message(dm_channel_id, text)
    )
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
        response = _call_with_rate_limit_retry(
            lambda: discord_api.send_channel_message(channel_id, message)
        )
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


def send_facebook_message(account_id: str, text: str) -> bool:
    if not PAGE_ACCESS_TOKEN:
        return False
    try:
        response = _call_with_rate_limit_retry(
            lambda: requests.post(
                "https://graph.facebook.com/v18.0/me/messages",
                params={"access_token": PAGE_ACCESS_TOKEN},
                json={"recipient": {"id": account_id}, "message": {"text": text}},
                timeout=10,
            )
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
        response = _call_with_rate_limit_retry(
            lambda: requests.post(
                "https://api.line.me/v2/bot/message/push",
                headers={
                    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={"to": account_id, "messages": [{"type": "text", "text": text}]},
                timeout=10,
            )
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


class PlatformNotificationSender:
    """Async application adapter over the existing synchronous platform APIs."""

    def __init__(self, delay_seconds: float = 0.5):
        self.delay_seconds = delay_seconds

    def _send(self, recipient: ReminderRecipient, message: str) -> bool:
        with _DELIVERY_LOCK:
            try:
                return send_notification(recipient, message)
            except Exception as error:
                log_event(
                    "external_send_failure",
                    "notifications",
                    level="error",
                    platform=recipient.platform.value,
                    status="error",
                    recipient_id=recipient.account_id,
                    operation="send_notification",
                    error=error,
                )
                return False
            finally:
                if self.delay_seconds > 0:
                    time.sleep(self.delay_seconds)

    async def send(self, recipient: ReminderRecipient, message: str) -> bool:
        return await asyncio.to_thread(self._send, recipient, message)
