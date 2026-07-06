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
