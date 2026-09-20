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

from ian.application.members import ReminderRecipient
from ian.domain.members import Platform
from ian.infrastructure.notifications.discord import DiscordHttpClient
from ian.utils.logging import log_event


_DELIVERY_LOCK = threading.Lock()


def call_with_rate_limit_retry(
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


class PlatformNotificationSender:
    """Deliver member notifications through Discord, Facebook, or LINE."""

    def __init__(
        self,
        discord: DiscordHttpClient,
        *,
        page_access_token: str,
        line_channel_access_token: str,
        delay_seconds: float = 0.5,
    ):
        self.discord = discord
        self.page_access_token = page_access_token
        self.line_channel_access_token = line_channel_access_token
        self.delay_seconds = delay_seconds

    def send_discord_dm(self, user_id: str, text: str) -> bool:
        response = call_with_rate_limit_retry(
            lambda: self.discord.create_dm_channel(user_id)
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
        message_response = call_with_rate_limit_retry(
            lambda: self.discord.send_channel_message(dm_channel_id, text)
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

    def send_facebook_message(self, account_id: str, text: str) -> bool:
        if not self.page_access_token:
            return False
        try:
            response = call_with_rate_limit_retry(
                lambda: requests.post(
                    "https://graph.facebook.com/v18.0/me/messages",
                    params={"access_token": self.page_access_token},
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

    def send_line_message(self, account_id: str, text: str) -> bool:
        if not self.line_channel_access_token:
            return False
        try:
            response = call_with_rate_limit_retry(
                lambda: requests.post(
                    "https://api.line.me/v2/bot/message/push",
                    headers={
                        "Authorization": f"Bearer {self.line_channel_access_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "to": account_id,
                        "messages": [{"type": "text", "text": text}],
                    },
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

    def _dispatch(self, recipient: ReminderRecipient, message: str) -> bool:
        senders = {
            Platform.DISCORD: self.send_discord_dm,
            Platform.FB: self.send_facebook_message,
            Platform.LINE: self.send_line_message,
        }
        return senders[recipient.platform](recipient.account_id, message)

    def _send(self, recipient: ReminderRecipient, message: str) -> bool:
        with _DELIVERY_LOCK:
            try:
                return self._dispatch(recipient, message)
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


class DiscordOperationalNotifier:
    """Send operational messages to Discord channels."""

    def __init__(
        self,
        discord: DiscordHttpClient,
        *,
        bot_token: str,
        log_channel_id: str,
    ):
        self.discord = discord
        self.bot_token = bot_token
        self.log_channel_id = log_channel_id

    def _send_channel(self, channel_id: str | int, message: str) -> bool:
        try:
            response = call_with_rate_limit_retry(
                lambda: self.discord.send_channel_message(channel_id, message)
            )
            success = response.status_code in (200, 201)
            log_event(
                "discord_channel_message",
                "notifications",
                level="info" if success else "warning",
                platform="Discord",
                status="success" if success else "failure",
                channel_id=channel_id,
                http_status=response.status_code,
            )
            return success
        except Exception as error:
            log_event(
                "discord_channel_message",
                "notifications",
                level="error",
                platform="Discord",
                status="error",
                channel_id=channel_id,
                error=error,
            )
            return False

    async def send_channel(self, channel_id: str | int, message: str) -> bool:
        return await asyncio.to_thread(self._send_channel, channel_id, message)

    async def send_log(self, message: str) -> None:
        if not self.bot_token or not self.log_channel_id:
            return
        await self.send_channel(self.log_channel_id, message)
