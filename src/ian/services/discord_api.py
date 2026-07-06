# SPDX-FileCopyrightText: 2026 NTU AI Club
# SPDX-License-Identifier: GPL-3.0-or-later

import requests

from ian.config import DISCORD_BOT_TOKEN


API_BASE_URL = "https://discord.com/api/v10"
REQUEST_TIMEOUT = 10


def _bot_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }


def _post(endpoint: str, payload: dict) -> requests.Response:
    return requests.post(
        f"{API_BASE_URL}{endpoint}",
        headers=_bot_headers(),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )


def create_dm_channel(user_id: str) -> requests.Response:
    return _post("/users/@me/channels", {"recipient_id": user_id})


def send_channel_message(channel_id: str | int, message: str) -> requests.Response:
    return _post(f"/channels/{channel_id}/messages", {"content": message})
