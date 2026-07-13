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

import hashlib
import json
import sys
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, TextIO

from ian.config import TZ_TPE


LOG_LEVELS = frozenset({"debug", "info", "warning", "error", "critical"})
REDACTED = "[REDACTED]"
Identifier = str | int | None

_IDENTIFIER_FIELDS = frozenset(
    {
        "account_id",
        "channel_id",
        "interaction_id",
        "message_id",
        "recipient_id",
        "reply_token",
        "sender_id",
        "session_id",
        "user_id",
    }
)
_CONTENT_FIELDS = frozenset(
    {
        "content",
        "input",
        "message",
        "message_content",
        "prompt",
        "query",
        "raw_content",
        "request_body",
        "response",
        "text",
        "user_message",
    }
)
_RESERVED_FIELDS = frozenset(
    {
        "timestamp",
        "level",
        "event",
        "component",
        "platform",
        "status",
        "duration_ms",
        "error_type",
        "correlation_id",
    }
)


def elapsed_ms(started_at: float) -> float:
    """Return elapsed monotonic time in milliseconds."""
    return (time.monotonic() - started_at) * 1000


def _stable_hash(value: Identifier) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def hash_identifier(identifier: Identifier) -> str:
    """Return a stable pseudonym for an identifier used in log correlation."""
    return _stable_hash(identifier)


def hash_account_id(account_id: Identifier) -> str:
    """Return a stable pseudonym for a platform account identifier."""
    return hash_identifier(account_id)


def hash_email(email: str | None) -> str:
    """Return a stable, case-insensitive pseudonym for an email address."""
    if email is None:
        return ""
    return _stable_hash(str(email).strip().lower())


def redact_token(token: str | None) -> str:
    """Remove a token or secret while preserving whether a value was present."""
    if token is None:
        return ""
    return REDACTED if str(token).strip() else ""


def redact_user_content(content: str | None) -> str:
    """Remove raw user content and retain only its character count."""
    if content is None:
        return ""
    text = str(content)
    return f"[REDACTED content_length={len(text)}]" if text else ""


def _redaction_kind(field_name: str) -> str | None:
    normalized = field_name.lower()
    if (
        "token" in normalized
        or "secret" in normalized
        or normalized.endswith("api_key")
        or normalized == "authorization"
    ):
        return "token"
    if normalized == "email" or normalized.endswith("_email"):
        return "email"
    if normalized in _IDENTIFIER_FIELDS or normalized.endswith("_account_id"):
        return "identifier"
    if normalized in _CONTENT_FIELDS or normalized.endswith("_content"):
        return "content"
    return None


def _as_identifier(value: Any) -> Identifier:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return str(value)


def _as_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _sanitize_value(field_name: str, value: Any) -> Any:
    kind = _redaction_kind(field_name)
    if kind == "token":
        return redact_token(_as_text(value))
    if kind == "email":
        return hash_email(_as_text(value))
    if kind == "identifier":
        return hash_account_id(_as_identifier(value))
    if kind == "content":
        return redact_user_content(_as_text(value))
    if isinstance(value, Mapping):
        return {str(key): _sanitize_value(str(key), item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(field_name, item) for item in value]
    return value


def sanitize_log_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the default sensitive-field policy to structured log fields."""
    return {str(key): _sanitize_value(str(key), value) for key, value in fields.items()}


class StructuredLogger:
    """Emit sanitized JSON Lines to stderr or another local text stream."""

    def __init__(
        self,
        *,
        stream: TextIO | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._stream = stream
        self._clock = clock or (lambda: datetime.now(TZ_TPE))
        self._lock = threading.Lock()

    def emit(
        self,
        event: str,
        component: str,
        *,
        level: str = "info",
        platform: str | None = None,
        status: str | None = None,
        duration_ms: float | int | None = None,
        error: BaseException | None = None,
        correlation_id: str | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        if level not in LOG_LEVELS:
            raise ValueError(f"Unsupported log level: {level}")
        if not isinstance(event, str) or not event.strip():
            raise ValueError("event and component are required")
        if not isinstance(component, str) or not component.strip():
            raise ValueError("event and component are required")

        conflicting = _RESERVED_FIELDS.intersection(fields)
        if conflicting:
            names = ", ".join(sorted(conflicting))
            raise ValueError(f"Reserved log fields must use named parameters: {names}")

        timestamp = self._clock()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=TZ_TPE)
        timestamp = timestamp.astimezone(TZ_TPE)

        entry: dict[str, Any] = {
            "timestamp": timestamp.isoformat(),
            "level": level,
            "event": event,
            "component": component,
        }
        optional = {
            "platform": platform,
            "status": status,
            "duration_ms": duration_ms,
            "error_type": type(error).__name__ if error is not None else None,
            "correlation_id": correlation_id,
        }
        entry.update({key: value for key, value in optional.items() if value is not None})
        entry.update(sanitize_log_fields(fields))

        payload = json.dumps(
            entry,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
            allow_nan=False,
        )
        stream = self._stream or sys.stderr
        with self._lock:
            stream.write(payload + "\n")
            stream.flush()
        return entry


_application_logger = StructuredLogger()


def log_event(event: str, component: str, **kwargs: Any) -> dict[str, Any]:
    """Emit an application event through the shared structured logger."""
    return _application_logger.emit(event, component, **kwargs)
