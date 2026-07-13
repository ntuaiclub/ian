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

from ian.gateways import facebook_webhook, line_webhook, webhook_server
from ian.config import MEMBER_MAPPING_FILE


def test_webhook_post_delegates_facebook_messages(monkeypatch):
    calls = []

    def fake_handle_facebook_messages(data):
        calls.append(data)

    monkeypatch.setattr(facebook_webhook, "handle_facebook_messages", fake_handle_facebook_messages)

    client = webhook_server.app.test_client()
    response = client.post("/", json={"object": "page", "entry": []})

    assert response.status_code == 200
    assert response.text == "ok"
    assert calls == [{"object": "page", "entry": []}]


def test_facebook_webhook_route_can_be_disabled(monkeypatch):
    calls = []

    def fake_handle_facebook_messages(data):
        calls.append(data)

    monkeypatch.setattr(facebook_webhook, "handle_facebook_messages", fake_handle_facebook_messages)
    webhook_server.configure_platforms("line")

    try:
        client = webhook_server.app.test_client()
        response = client.post("/", json={"object": "page", "entry": []})

        assert response.status_code == 404
        assert calls == []
    finally:
        webhook_server.configure_platforms("all")


def test_line_webhook_route_can_be_disabled(monkeypatch):
    calls = []

    def fake_handle(body, signature):
        calls.append({"body": body, "signature": signature})

    monkeypatch.setattr(line_webhook.line_handler, "handle", fake_handle)
    webhook_server.configure_platforms("fb")

    try:
        client = webhook_server.app.test_client()
        response = client.post(
            "/line/callback",
            data="{}",
            headers={"X-Line-Signature": "signature"},
        )

        assert response.status_code == 404
        assert calls == []
    finally:
        webhook_server.configure_platforms("all")


def test_webhook_status_reports_enabled_platforms():
    webhook_server.configure_platforms("line")

    try:
        client = webhook_server.app.test_client()
        response = client.get("/status")

        assert response.status_code == 200
        assert response.json["platforms"] == ["LINE"]
    finally:
        webhook_server.configure_platforms("all")


def test_entrypoint_initializes_dependencies_before_starting_server(monkeypatch):
    calls = []
    monkeypatch.setattr(
        webhook_server,
        "initialize_dependencies",
        lambda: calls.append(("initialize",)),
    )
    monkeypatch.setattr(
        webhook_server.app,
        "run",
        lambda **kwargs: calls.append(("run", kwargs)),
    )

    webhook_server.entrypoint("line")

    assert calls == [
        ("initialize",),
        ("run", {"host": "0.0.0.0", "port": 5190, "debug": False}),
    ]
    webhook_server.configure_platforms("all")


def test_facebook_member_mapping_path_comes_from_config():
    assert facebook_webhook.MAPPING_FILE_PATH == MEMBER_MAPPING_FILE
    assert MEMBER_MAPPING_FILE.name == "member_mapping.csv"
    assert MEMBER_MAPPING_FILE.parent.name == "data"
