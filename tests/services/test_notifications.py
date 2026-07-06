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

from ian.services.notifications import format_staff_notification, is_staff_role


def test_is_staff_role_matches_staff_keywords():
    assert is_staff_role("技術部部員")
    assert is_staff_role("社長")
    assert not is_staff_role("一般社員")


def test_format_staff_notification_includes_event_and_note():
    message = format_staff_notification(
        {
            "title": "Demo",
            "date": "2026/03/07",
            "weekday": "六",
            "time": "19:00",
            "venue": "新生",
            "speaker": "講者",
            "outline": "大綱",
            "target": "社員",
            "livestream": "Y",
            "recording": "N",
            "online_link": "https://meet.example",
            "slides": "",
        },
        note="請準時",
    )

    assert "Demo" in message
    assert "線上直播" in message
    assert "請準時" in message
