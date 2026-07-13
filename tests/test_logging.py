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

import io
import json
from datetime import UTC, datetime

import pytest

from ian.config import TZ_TPE
from ian.utils.logging import (
    REDACTED,
    StructuredLogger,
    elapsed_ms,
    hash_account_id,
    hash_email,
    hash_identifier,
    log_event,
    redact_token,
    redact_user_content,
    sanitize_log_fields,
)


def test_structured_logger_emits_json_line_with_standard_fields():
    stream = io.StringIO()
    logger = StructuredLogger(
        stream=stream,
        clock=lambda: datetime(2026, 7, 13, 9, 2, 3, tzinfo=TZ_TPE),
    )

    entry = logger.emit(
        "request_completed",
        "webhook",
        platform="LINE",
        status="success",
        duration_ms=12.5,
        correlation_id="request-1",
        result_count=2,
    )

    assert json.loads(stream.getvalue()) == entry == {
        "timestamp": "2026-07-13T09:02:03+08:00",
        "level": "info",
        "event": "request_completed",
        "component": "webhook",
        "platform": "LINE",
        "status": "success",
        "duration_ms": 12.5,
        "correlation_id": "request-1",
        "result_count": 2,
    }
    assert stream.getvalue().endswith("\n")


def test_shared_logger_preserves_stderr_console_workflow(capsys):
    log_event("service_started", "reminder", status="success")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["event"] == "service_started"


def test_structured_logger_interprets_naive_clock_in_project_timezone():
    stream = io.StringIO()
    logger = StructuredLogger(
        stream=stream,
        clock=lambda: datetime(2026, 7, 13, 9, 2, 3),
    )

    logger.emit("service_started", "reminder")

    assert json.loads(stream.getvalue())["timestamp"] == "2026-07-13T09:02:03+08:00"


def test_structured_logger_converts_aware_clock_to_project_timezone():
    stream = io.StringIO()
    logger = StructuredLogger(
        stream=stream,
        clock=lambda: datetime(2026, 7, 13, 1, 2, 3, tzinfo=UTC),
    )

    logger.emit("service_started", "reminder")

    assert json.loads(stream.getvalue())["timestamp"] == "2026-07-13T09:02:03+08:00"


def test_structured_logger_emits_one_json_object_per_line():
    stream = io.StringIO()
    logger = StructuredLogger(stream=stream)

    logger.emit("service_started", "reminder")
    logger.emit("service_stopped", "reminder")

    entries = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [entry["event"] for entry in entries] == [
        "service_started",
        "service_stopped",
    ]


@pytest.mark.parametrize(
    ("helper", "first", "second"),
    [
        pytest.param(hash_account_id, "account-123", "account-456", id="account-id"),
        pytest.param(hash_email, "Member@Example.test", "other@example.test", id="email"),
    ],
)
def test_hash_helpers_are_stable_without_exposing_values(helper, first, second):
    hashed = helper(first)

    assert hashed == helper(first)
    assert hashed != helper(second)
    assert first.lower() not in hashed
    assert hashed.startswith("sha256:")


def test_email_hashing_is_case_insensitive():
    assert hash_email("Member@Example.test") == hash_email("member@example.test")


def test_account_id_hashing_accepts_numeric_and_missing_identifiers():
    assert hash_account_id(12345).startswith("sha256:")
    assert hash_account_id(None) == ""


def test_generic_identifier_hash_matches_account_hashing_policy():
    assert hash_identifier("identifier-1") == hash_account_id("identifier-1")


def test_elapsed_ms_uses_monotonic_clock(monkeypatch):
    monkeypatch.setattr("ian.utils.logging.time.monotonic", lambda: 12.345)

    assert elapsed_ms(10.0) == pytest.approx(2345.0)


@pytest.mark.parametrize(
    ("helper", "value"),
    [
        pytest.param(hash_account_id, "", id="empty-account-id"),
        pytest.param(hash_account_id, "   ", id="blank-account-id"),
        pytest.param(hash_email, None, id="missing-email"),
        pytest.param(hash_email, "", id="empty-email"),
        pytest.param(hash_email, "   ", id="blank-email"),
    ],
)
def test_hash_helpers_treat_empty_or_blank_values_as_missing(helper, value):
    assert helper(value) == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("secret-token", REDACTED, id="token"),
        pytest.param("", "", id="empty-token"),
        pytest.param(None, "", id="missing-token"),
    ],
)
def test_redact_token_removes_secret(value, expected):
    assert redact_token(value) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(None, "", id="missing"),
        pytest.param("", "", id="empty"),
        pytest.param("private user question", 21, id="ascii"),
        pytest.param("台灣 AI", 5, id="unicode"),
    ],
)
def test_redact_user_content_preserves_only_length(raw, expected):
    redacted = redact_user_content(raw)

    if isinstance(expected, int):
        assert redacted == f"[REDACTED content_length={expected}]"
        assert raw not in redacted
    else:
        assert redacted == expected


def test_sanitize_log_fields_redacts_nested_sensitive_values():
    fields = sanitize_log_fields(
        {
            "account_id": "account-123",
            "email": "member@example.test",
            "access_token": "token-123",
            "user_message": "private question",
            "query": "private search",
            "context": {
                "sender_id": "sender-123",
                "api_key": "key-123",
            },
            "safe_count": 3,
        }
    )

    serialized = json.dumps(fields)
    for sensitive in (
        "account-123",
        "member@example.test",
        "token-123",
        "private question",
        "private search",
        "sender-123",
        "key-123",
    ):
        assert sensitive not in serialized
    assert fields["access_token"] == REDACTED
    assert fields["context"]["api_key"] == REDACTED
    assert fields["safe_count"] == 3


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        pytest.param("backup_account_id", "account-123", id="account-id-suffix"),
        pytest.param("contact_email", "member@example.test", id="email-suffix"),
        pytest.param("oauth_token_value", "token-123", id="token-substring"),
        pytest.param("generated_content", "private answer", id="content-suffix"),
        pytest.param("authorization", "Bearer secret", id="authorization"),
    ],
)
def test_sanitize_log_fields_applies_sensitive_field_naming_rules(field_name, value):
    sanitized = sanitize_log_fields({field_name: value})

    assert value not in json.dumps(sanitized)


def test_sanitize_log_fields_handles_nested_sequences_and_non_string_values():
    fields = sanitize_log_fields(
        {
            "items": [
                {"account_id": 12345},
                {"email": None},
                {"user_message": "private question"},
            ],
            "flags": (True, False),
        }
    )

    serialized = json.dumps(fields)
    assert fields["items"][0]["account_id"].startswith("sha256:")
    assert fields["items"][1]["email"] == ""
    assert fields["flags"] == [True, False]
    assert "12345" not in serialized
    assert "private question" not in serialized


def test_sanitize_log_fields_coerces_unexpected_identifier_types_before_hashing():
    fields = sanitize_log_fields({"account_id": True})

    assert fields["account_id"] == hash_account_id("True")


def test_structured_logger_records_error_type_without_error_message():
    stream = io.StringIO()
    logger = StructuredLogger(stream=stream)

    logger.emit(
        "operation_failed",
        "member_store",
        level="error",
        status="error",
        error=RuntimeError("token-123 leaked"),
    )

    entry = json.loads(stream.getvalue())
    assert entry["error_type"] == "RuntimeError"
    assert "token-123" not in stream.getvalue()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        pytest.param({"level": "verbose"}, "Unsupported log level", id="level"),
        pytest.param({"event": ""}, "event and component are required", id="event"),
        pytest.param({"event": "   "}, "event and component are required", id="blank-event"),
        pytest.param(
            {"component": "   "},
            "event and component are required",
            id="blank-component",
        ),
        pytest.param(
            {"fields": {"timestamp": "override"}},
            "Reserved log fields",
            id="reserved-field",
        ),
    ],
)
def test_structured_logger_rejects_invalid_schema(kwargs, message):
    logger = StructuredLogger(stream=io.StringIO())
    event = kwargs.pop("event", "event")
    component = kwargs.pop("component", "component")
    fields = kwargs.pop("fields", {})

    with pytest.raises(ValueError, match=message):
        logger.emit(event, component, **kwargs, **fields)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
    ],
)
def test_structured_logger_rejects_non_finite_numbers_that_are_invalid_json(value):
    stream = io.StringIO()
    logger = StructuredLogger(stream=stream)

    with pytest.raises(ValueError, match="JSON compliant"):
        logger.emit("measurement_recorded", "metrics", measurement=value)

    assert stream.getvalue() == ""
