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

from ian.services.member_cache import MemberCache


def test_member_cache_loads_and_saves_json_file(tmp_path):
    cache_file = tmp_path / "member_db.json"
    cache_file.write_text(
        '[{"id": "Alice", "email": "alice@example.com"}]', encoding="utf-8"
    )
    cache = MemberCache(cache_file)

    assert cache.load() == [{"id": "Alice", "email": "alice@example.com"}]

    cache.replace_all([{"id": "Bob", "email": "bob@example.com"}])
    cache.save()

    assert cache_file.read_text(encoding="utf-8") == (
        '[\n  {\n    "id": "Bob",\n    "email": "bob@example.com"\n  }\n]'
    )


def test_member_cache_load_returns_none_when_file_is_missing(tmp_path):
    cache = MemberCache(tmp_path / "missing.json")

    assert cache.load() is None
    assert cache.all() == []


def test_member_cache_finds_members_by_platform_and_email(tmp_path):
    cache = MemberCache(
        tmp_path / "member_db.json",
        [
            {
                "id": "Alice",
                "email": "Alice@Example.COM",
                "discord_acc_id": " discord-1 ",
            },
            {"id": "Bob", "email": "bob@example.com", "discord_acc_id": ""},
        ],
    )

    assert cache.find_by_platform("Discord", "discord-1")["id"] == "Alice"
    assert cache.find_by_platform("Discord", "missing") is None
    assert cache.find_by_platform("Slack", "discord-1") is None
    assert cache.find_by_email("alice@Example.COM")["id"] == "Alice"
    assert cache.find_by_email("ALICE@example.com")["id"] == "Alice"


def test_member_cache_update_field_mutates_matching_email_only(tmp_path):
    cache = MemberCache(
        tmp_path / "member_db.json",
        [
            {"email": "alice@example.com", "subscribe": ""},
            {"email": "bob@example.com", "subscribe": ""},
        ],
    )

    assert cache.update_field("ALICE@example.com", "subscribe", "discord")
    assert cache.all() == [
        {"email": "alice@example.com", "subscribe": "discord"},
        {"email": "bob@example.com", "subscribe": ""},
    ]
    assert not cache.update_field("missing@example.com", "subscribe", "discord")
