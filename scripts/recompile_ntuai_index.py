#!/usr/bin/env python3
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

"""Compile the NTUAI Markdown knowledge base into deterministic JSONL."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "ntuai_zh_base.md"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "ntuai_recompiled_index.jsonl"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
QUESTION_RE = re.compile(r"^\s*\*\*Q:\*\*\s*(.+?)\s*$", re.IGNORECASE)
ANSWER_RE = re.compile(r"^\s*\*\*A:\*\*\s*(.*?)\s*$", re.IGNORECASE)
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)


class CompileError(ValueError):
    """Raised when the Markdown cannot be compiled safely."""


@dataclass(frozen=True)
class Section:
    path: tuple[str, ...]
    lines: tuple[str, ...]

    @property
    def title(self) -> str:
        return self.path[-1]

    @property
    def display_path(self) -> str:
        return " > ".join(self.path)


def _clean_heading(value: str) -> str:
    value = re.sub(r"\s+#+\s*$", "", value).strip()
    return value.replace("**", "").strip()


def _trim_block(lines: Sequence[str]) -> str:
    cleaned = list(lines)
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()

    result: list[str] = []
    previous_blank = False
    for line in cleaned:
        line = line.rstrip()
        is_blank = not line.strip()
        if is_blank and previous_blank:
            continue
        result.append(line)
        previous_blank = is_blank
    return "\n".join(result).strip()


def parse_sections(markdown: str) -> list[Section]:
    """Split Markdown into heading-aware sections without external parsers."""
    sections: list[Section] = []
    headings: list[str] = []
    current_path: tuple[str, ...] | None = None
    current_lines: list[str] = []
    active_fence: str | None = None

    def finish_current() -> None:
        nonlocal current_lines
        if current_path is not None:
            sections.append(Section(current_path, tuple(current_lines)))
        current_lines = []

    for line in markdown.splitlines():
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)[0]
            if active_fence is None:
                active_fence = marker
            elif marker == active_fence:
                active_fence = None
            if current_path is not None:
                current_lines.append(line)
            continue

        heading_match = HEADING_RE.match(line) if active_fence is None else None
        if heading_match:
            finish_current()
            level = len(heading_match.group(1))
            title = _clean_heading(heading_match.group(2))
            if not title:
                raise CompileError("Markdown contains an empty heading")
            headings = headings[: level - 1]
            headings.append(title)
            current_path = tuple(headings)
            continue

        if current_path is None:
            if line.strip():
                current_path = ("未分類",)
            else:
                continue
        current_lines.append(line)

    finish_current()
    return sections


def _extract_section_content(
    section: Section,
) -> tuple[str, list[tuple[str, str]]]:
    """Return non-FAQ content and validated Q/A pairs from one section."""
    paragraph_lines: list[str] = []
    faq_pairs: list[tuple[str, str]] = []
    lines = list(section.lines)
    index = 0
    active_fence: str | None = None

    while index < len(lines):
        line = lines[index]
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)[0]
            active_fence = marker if active_fence is None else None
            paragraph_lines.append(line)
            index += 1
            continue

        question_match = QUESTION_RE.match(line) if active_fence is None else None
        answer_match = ANSWER_RE.match(line) if active_fence is None else None
        if answer_match:
            raise CompileError(
                f"{section.display_path}: found **A:** without a preceding **Q:**"
            )
        if not question_match:
            paragraph_lines.append(line)
            index += 1
            continue

        question = question_match.group(1).strip()
        index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines) or not ANSWER_RE.match(lines[index]):
            raise CompileError(
                f"{section.display_path}: question has no following **A:**: {question}"
            )

        answer_header = ANSWER_RE.match(lines[index])
        assert answer_header is not None
        answer_lines = [answer_header.group(1)] if answer_header.group(1) else []
        index += 1
        answer_fence: str | None = None
        while index < len(lines):
            answer_line = lines[index]
            answer_fence_match = FENCE_RE.match(answer_line)
            if answer_fence_match:
                marker = answer_fence_match.group(1)[0]
                answer_fence = marker if answer_fence is None else None
            if answer_fence is None and QUESTION_RE.match(answer_line):
                break
            if answer_fence is None and ANSWER_RE.match(answer_line):
                raise CompileError(
                    f"{section.display_path}: found a second **A:** before the next **Q:**"
                )
            answer_lines.append(answer_line)
            index += 1

        answer = _trim_block(answer_lines)
        if not question or not answer:
            raise CompileError(
                f"{section.display_path}: FAQ question and answer must be non-empty"
            )
        faq_pairs.append((question, answer))

    return _trim_block(paragraph_lines), faq_pairs


def _split_table_row(line: str) -> list[str]:
    return [
        cell.strip().replace("**", "") for cell in line.strip().strip("|").split("|")
    ]


def _is_table_separator(cells: Sequence[str]) -> bool:
    return bool(cells) and all(
        re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells
    )


def _membership_entity(
    sections: Sequence[Section], source_file: str
) -> dict[str, Any] | None:
    fee_section = next(
        (section for section in sections if section.title.startswith("社費資訊")), None
    )
    if fee_section is None:
        return None

    table_rows = [
        _split_table_row(line)
        for line in fee_section.lines
        if line.strip().startswith("|")
    ]
    table_rows = [row for row in table_rows if not _is_table_separator(row)]
    if len(table_rows) < 2:
        return None

    headers = table_rows[0]
    plans: dict[str, dict[str, Any]] = {}
    plan_columns: dict[int, str] = {}
    for column, header in enumerate(headers[1:], start=1):
        match = re.fullmatch(r"(.+?)\s+\$([\d,]+)\*?", header)
        if not match:
            continue
        name = match.group(1).strip()
        plans[name] = {"amount": int(match.group(2).replace(",", ""))}
        plan_columns[column] = name

    if not plans:
        return None

    for row in table_rows[1:]:
        if not row:
            continue
        label = row[0]
        for column, name in plan_columns.items():
            if column >= len(row):
                continue
            value = row[column].strip()
            if label == "社員身份有效期" and value:
                plans[name]["duration"] = value
            elif value and value != "○":
                plans[name].setdefault("benefits", []).append(label)

    def section_text(title: str) -> str:
        section = next((item for item in sections if item.title == title), None)
        return _trim_block(section.lines) if section else ""

    payment_text = section_text("付款方式")
    account_match = re.search(r"帳號[：:]\s*([\d\s]+)", payment_text)
    bank_id_match = re.search(r"(?:Bank ID|郵局代號)[）)]?[：:]\s*(\d+)", payment_text)
    method = ""
    for line in payment_text.splitlines():
        candidate = re.sub(r"^\s*[-*+]\s*", "", line).strip()
        if candidate and "轉帳" in candidate:
            method = candidate
            break

    entity: dict[str, Any] = {
        "id": "entity_membership_fee",
        "type": "entity",
        "entity_type": "membership_fee",
        "name": "社費政策",
        "plans": plans,
        "source_file": source_file,
        "lang": "zh",
    }
    optional_values: dict[str, Any] = {
        "refund_policy": section_text("退費"),
        "reward_policy": section_text("獎勵"),
        "notes": section_text("備註"),
        "payment": {
            key: value
            for key, value in {
                "bank_account": re.sub(r"\s+", "", account_match.group(1))
                if account_match
                else "",
                "bank_id": bank_id_match.group(1) if bank_id_match else "",
                "method": method,
            }.items()
            if value
        },
    }
    entity.update({key: value for key, value in optional_values.items() if value})
    return entity


def _contact_entity(
    sections: Sequence[Section], source_file: str
) -> dict[str, Any] | None:
    contact_sections = [
        section
        for section in sections
        if "聯絡" in section.title or "社群" in section.title
    ]
    content = "\n".join("\n".join(section.lines) for section in contact_sections)
    emails = list(dict.fromkeys(EMAIL_RE.findall(content)))
    urls = [url.rstrip(".,;:!?，。！、）]") for url in URL_RE.findall(content)]
    urls = list(dict.fromkeys(urls))
    if not emails and not urls:
        return None
    return {
        "id": "entity_contact",
        "type": "entity",
        "entity_type": "contact",
        "name": "聯絡資訊與社群",
        "emails": emails,
        "urls": urls,
        "source_file": source_file,
        "lang": "zh",
    }


def _schedule_entity(
    sections: Sequence[Section], source_file: str
) -> dict[str, Any] | None:
    schedule_section = next(
        (
            section
            for section in sections
            if section.title == "時間" and "社課與活動" in section.path
        ),
        None,
    )
    if schedule_section is None:
        return None
    schedule = _trim_block(schedule_section.lines)
    if not schedule:
        return None
    return {
        "id": "entity_course_schedule",
        "type": "entity",
        "entity_type": "course_schedule",
        "name": "社課與活動時間",
        "schedule": schedule,
        "source_file": source_file,
        "lang": "zh",
    }


def validate_records(records: Sequence[dict[str, Any]]) -> None:
    """Validate the JSONL contract before replacing the existing file."""
    seen_ids: set[str] = set()
    for index, record in enumerate(records, start=1):
        record_id = record.get("id")
        record_type = record.get("type")
        if not isinstance(record_id, str) or not record_id:
            raise CompileError(f"record {index} has no non-empty string id")
        if record_id in seen_ids:
            raise CompileError(f"duplicate record id: {record_id}")
        seen_ids.add(record_id)
        if record_type not in {"paragraph", "faq", "entity"}:
            raise CompileError(f"{record_id}: unsupported type {record_type!r}")
        if not isinstance(record.get("source_file"), str) or not record["source_file"]:
            raise CompileError(f"{record_id}: source_file is required")
        if record.get("lang") != "zh":
            raise CompileError(f"{record_id}: lang must be 'zh'")

        if record_type == "paragraph":
            required = ("path", "text")
        elif record_type == "faq":
            required = ("path", "question", "answer", "tags")
        else:
            required = ("entity_type", "name")
        for key in required:
            if key not in record or record[key] in (None, ""):
                raise CompileError(f"{record_id}: {key} is required")

        try:
            json.dumps(record, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise CompileError(
                f"{record_id}: not JSON serializable: {error}"
            ) from error


def compile_markdown(markdown: str, source_file: str) -> list[dict[str, Any]]:
    sections = parse_sections(markdown)
    paragraph_drafts: list[tuple[Section, str]] = []
    faq_drafts: list[tuple[Section, str, str]] = []
    for section in sections:
        paragraph, faq_pairs = _extract_section_content(section)
        if paragraph:
            paragraph_drafts.append((section, paragraph))
        faq_drafts.extend((section, question, answer) for question, answer in faq_pairs)

    records: list[dict[str, Any]] = []
    for index, (section, text) in enumerate(paragraph_drafts, start=1):
        records.append(
            {
                "id": f"para_{index:04d}",
                "type": "paragraph",
                "text": text,
                "path": section.display_path,
                "source_file": source_file,
                "lang": "zh",
            }
        )
    for index, (section, question, answer) in enumerate(faq_drafts, start=1):
        records.append(
            {
                "id": f"faq_{index:04d}",
                "type": "faq",
                "question": question,
                "answer": answer,
                "path": section.display_path,
                "tags": list(section.path),
                "source_file": source_file,
                "lang": "zh",
            }
        )

    for entity in (
        _membership_entity(sections, source_file),
        _contact_entity(sections, source_file),
        _schedule_entity(sections, source_file),
    ):
        if entity is not None:
            records.append(entity)

    if not records:
        raise CompileError("Markdown produced no index records")
    validate_records(records)
    return records


def serialize_jsonl(records: Sequence[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
        for record in records
    )


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        Path(temporary_name).replace(path)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compile ntuai_zh_base.md into the RAG JSONL index."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when the output is missing or stale; do not write it.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        markdown = args.input.read_text(encoding="utf-8")
        records = compile_markdown(markdown, args.input.name)
        compiled = serialize_jsonl(records)
    except (OSError, UnicodeError, CompileError) as error:
        print(f"compile failed: {error}")
        return 2

    if args.check:
        try:
            current = args.output.read_text(encoding="utf-8")
        except FileNotFoundError:
            current = ""
        except (OSError, UnicodeError) as error:
            print(f"check failed: {error}")
            return 2
        if current != compiled:
            print(f"stale: {args.output}")
            return 1
        print(f"up to date: {args.output} ({len(records)} records)")
        return 0

    try:
        write_atomic(args.output, compiled)
    except OSError as error:
        print(f"write failed: {error}")
        return 2
    print(f"compiled {len(records)} records: {args.input} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
