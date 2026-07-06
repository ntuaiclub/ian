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

import pytest
import requests

from ian.services.member_api import MemberApiError, fetch_members, update_member_fields


class FakeResponse:
    def __init__(self, payload, *, raises=None):
        self._payload = payload
        self._raises = raises

    def raise_for_status(self):
        if self._raises:
            raise self._raises

    def json(self):
        return self._payload


def test_fetch_members_returns_api_data(monkeypatch):
    calls = []

    def fake_get(url, *, params, timeout, allow_redirects):
        calls.append((url, params, timeout, allow_redirects))
        return FakeResponse({"status": "success", "data": [{"id": "Alice"}]})

    monkeypatch.setattr(requests, "get", fake_get)

    assert fetch_members("https://api.example.test/members", "secret") == [{"id": "Alice"}]
    assert calls == [
        (
            "https://api.example.test/members",
            {"api_key": "secret"},
            30,
            True,
        )
    ]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"status": "error", "message": "bad key"}, "bad key"),
        ({"status": "failed"}, "failed"),
        ({"status": "success", "data": []}, "empty data"),
    ],
)
def test_fetch_members_raises_clear_error_for_failed_payloads(
    monkeypatch, payload, message
):
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: FakeResponse(payload),
    )

    with pytest.raises(MemberApiError, match=message):
        fetch_members("https://api.example.test/members", "secret")


def test_update_member_fields_posts_api_key_email_and_fields(monkeypatch):
    calls = []

    def fake_post(url, *, json, timeout, allow_redirects):
        calls.append((url, json, timeout, allow_redirects))
        return FakeResponse({"status": "success"})

    monkeypatch.setattr(requests, "post", fake_post)

    update_member_fields(
        "https://api.example.test/members",
        "secret",
        "alice@example.com",
        {"discord_acc_id": "discord-1"},
    )

    assert calls == [
        (
            "https://api.example.test/members",
            {
                "api_key": "secret",
                "email": "alice@example.com",
                "discord_acc_id": "discord-1",
            },
            30,
            True,
        )
    ]


def test_update_member_fields_raises_api_message_on_failure(monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: FakeResponse(
            {"status": "error", "message": "locked"}
        ),
    )

    with pytest.raises(MemberApiError, match="locked"):
        update_member_fields(
            "https://api.example.test/members",
            "secret",
            "alice@example.com",
            {"discord_acc_id": "discord-1"},
        )
