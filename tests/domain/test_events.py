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

from datetime import timedelta, timezone

import pytest
from pydantic import ValidationError

from ian.domain.events import Event, lexical_to_text


TPE = timezone(timedelta(hours=8))


def event_document(**overrides):
    document = {
        "id": 42,
        "title": " Event MCP workshop ",
        "startDate": "2026-08-01T19:00:00+08:00",
        "endDate": "2026-08-01T21:00:00+08:00",
        "slug": "event-mcp-workshop",
        "_status": "published",
    }
    document.update(overrides)
    return document


def test_event_normalizes_fields_and_exposes_required_tier():
    event = Event.model_validate(
        event_document(
            location="  Room 101 ",
            speaker="  Ian ",
            minimumTier=None,
            notes="  Bring a laptop.  ",
            ignored="not part of the domain",
        )
    )

    assert event.title == "Event MCP workshop"
    assert event.location == "Room 101"
    assert event.speaker == "Ian"
    assert event.notes == "Bring a laptop."
    assert event.required_tier == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": "   "},
        {"startDate": "2026-08-01T19:00:00"},
        {"endDate": "2026-08-01T18:59:59+08:00"},
        {"minimumTier": 4},
        {"onlineURL": "ftp://example.test/stream"},
        {"_status": "draft"},
    ],
)
def test_event_rejects_invalid_contract_values(overrides):
    with pytest.raises(ValidationError):
        Event.model_validate(event_document(**overrides))


def test_event_accepts_structured_public_urls_and_materials():
    event = Event.model_validate(
        event_document(
            onlineURL="https://example.test/live",
            videoURL="https://example.test/recording",
            materials=[
                {
                    "id": "slides",
                    "label": " Slides ",
                    "url": "https://example.test/slides",
                }
            ],
            eventMedia=[
                {
                    "id": 5,
                    "url": "https://example.test/photo.jpg",
                    "alt": " Photo ",
                }
            ],
        )
    )

    assert str(event.onlineURL) == "https://example.test/live"
    assert event.materials[0].label == "Slides"
    assert event.eventMedia[0].alt == "Photo"


def test_event_normalizes_null_event_media_from_mcp_to_an_empty_list():
    event = Event.model_validate(event_document(eventMedia=None))

    assert event.eventMedia == []


def test_lexical_to_text_extracts_text_and_preserves_block_boundaries():
    content = {
        "root": {
            "children": [
                {"type": "heading", "children": [{"text": "Title"}]},
                {
                    "type": "paragraph",
                    "children": [{"text": "Body "}, {"text": "text"}],
                },
                {"type": "unknown", "children": [{"text": "Still included"}]},
            ]
        }
    }

    assert lexical_to_text(content) == "Title\nBody text\nStill included"
    assert lexical_to_text({"root": {"children": []}}) == ""
