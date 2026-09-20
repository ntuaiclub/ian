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

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class EventSchemaError(ValueError):
    """Raised when an Event document violates Ian's data contract."""


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


class EventMaterial(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    label: str
    url: HttpUrl

    @field_validator("label")
    @classmethod
    def require_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("material label cannot be blank")
        return normalized


class EventMedia(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    url: HttpUrl
    alt: str | None = None

    @field_validator("alt")
    @classmethod
    def normalize_alt(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)


class Event(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: int
    title: str
    startDate: datetime
    endDate: datetime
    location: str | None = None
    content: dict[str, Any] | None = None
    minimumTier: int | None = Field(default=None, ge=0, le=3)
    speaker: str | None = None
    category: str | None = None
    audience: str | None = None
    enableLivestream: bool = False
    enableRecording: bool = False
    nonMemberFee: int | None = Field(default=None, ge=0)
    onlineURL: HttpUrl | None = None
    materials: list[EventMaterial] = Field(default_factory=list)
    videoURL: HttpUrl | None = None
    eventMedia: list[EventMedia] = Field(default_factory=list)
    notes: str | None = None
    slug: str
    status: Literal["published"] = Field(alias="_status")

    @field_validator("title")
    @classmethod
    def require_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("event title cannot be blank")
        return normalized

    @field_validator("location", "speaker", "category", "audience", "notes")
    @classmethod
    def normalize_optional_fields(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("eventMedia", mode="before")
    @classmethod
    def normalize_empty_media(cls, value: list[EventMedia] | None) -> list[EventMedia]:
        return [] if value is None else value

    @field_validator("startDate", "endDate")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event datetime must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_date_range(self) -> "Event":
        if self.endDate < self.startDate:
            raise ValueError("event endDate cannot precede startDate")
        return self

    @property
    def required_tier(self) -> int:
        return self.minimumTier or 0


def lexical_to_text(content: dict[str, Any] | None) -> str:
    """Extract plain text from Payload Lexical JSON without rendering markup."""
    if not content:
        return ""

    lines: list[str] = []
    separators = {"paragraph", "heading", "listitem"}

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        text = node.get("text")
        if isinstance(text, str) and text:
            lines.append(text)
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                visit(child)
        if node.get("type") in separators and lines and lines[-1] != "\n":
            lines.append("\n")

    root = content.get("root")
    if isinstance(root, dict):
        visit(root)
    return "".join(lines).strip()
