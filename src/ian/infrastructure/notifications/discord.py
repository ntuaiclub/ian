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


API_BASE_URL = "https://discord.com/api/v10"
REQUEST_TIMEOUT = 10


class DiscordHttpClient:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bot {self.bot_token}",
            "Content-Type": "application/json",
        }

    def _post(self, endpoint: str, payload: dict) -> requests.Response:
        return requests.post(
            f"{API_BASE_URL}{endpoint}",
            headers=self._headers(),
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

    def create_dm_channel(self, user_id: str) -> requests.Response:
        return self._post("/users/@me/channels", {"recipient_id": user_id})

    def send_channel_message(
        self,
        channel_id: str | int,
        message: str,
    ) -> requests.Response:
        return self._post(f"/channels/{channel_id}/messages", {"content": message})
