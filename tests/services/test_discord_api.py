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

from ian.infrastructure.notifications import discord as discord_transport


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_create_dm_channel_posts_recipient_with_bot_headers(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse(200, {"id": "dm-1"})

    monkeypatch.setattr(discord_transport.requests, "post", fake_post)
    client = discord_transport.DiscordHttpClient("bot-token")

    response = client.create_dm_channel("user-1")

    assert response.json() == {"id": "dm-1"}
    assert calls == [
        {
            "url": "https://discord.com/api/v10/users/@me/channels",
            "headers": {
                "Authorization": "Bot bot-token",
                "Content-Type": "application/json",
            },
            "json": {"recipient_id": "user-1"},
            "timeout": 10,
        }
    ]


def test_send_channel_message_posts_content_with_bot_headers(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse(201, {"id": "message-1"})

    monkeypatch.setattr(discord_transport.requests, "post", fake_post)
    client = discord_transport.DiscordHttpClient("bot-token")

    response = client.send_channel_message("channel-1", "hello")

    assert response.status_code == 201
    assert calls == [
        {
            "url": "https://discord.com/api/v10/channels/channel-1/messages",
            "headers": {
                "Authorization": "Bot bot-token",
                "Content-Type": "application/json",
            },
            "json": {"content": "hello"},
            "timeout": 10,
        }
    ]
