import re
from datetime import datetime
from typing import Any

import pandas as pd

from ian.config import TZ_TPE


MEMBER_ONLY_FIELDS = ["線上連結", "錄影檔案", "課程照片", "課程講義", "備註"]

COMMON_COLUMN_NAMES = [
    "週次",
    "時間",
    "星期",
    "活動時間",
    "場地",
    "是否直播",
    "是否錄影",
    "社課主題/活動名稱",
    "講者",
    "社課類別",
    "課程大綱",
    "課程對象",
    "非社員報名費用",
    "線上連結",
    "錄影檔案",
    "課程照片",
    "課程講義",
    "備註",
]

DATE_FULL_RE = re.compile(r"(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})")
DATE_SHORT_RE = re.compile(r"^(\d{1,2})[/\-](\d{1,2})$")


def clean_value(value: Any) -> str:
    text = str(value).strip() if pd.notna(value) else ""
    return "" if text.lower() in ("nan", "-", "無") else text


def normalize_date(year: int, month: int, day: int) -> str:
    return f"{year:04d}/{month:02d}/{day:02d}"


def parse_dates_from_query(query: str, current_year: int | None = None) -> list[str]:
    year = current_year or datetime.now(TZ_TPE).year
    dates = []
    for match in DATE_FULL_RE.finditer(query):
        dates.append(
            normalize_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        )
    if not dates:
        match = DATE_SHORT_RE.match(query.strip())
        if match:
            dates.append(normalize_date(year, int(match.group(1)), int(match.group(2))))
    return dates


def get_column_mapping(df: pd.DataFrame) -> dict[str, str]:
    column_mapping = {}
    for col in df.columns:
        original_col = str(col)
        if r"\x" in original_col:
            col_index = list(df.columns).index(col)
            if col_index < len(COMMON_COLUMN_NAMES):
                column_mapping[col] = COMMON_COLUMN_NAMES[col_index]
            else:
                column_mapping[col] = f"欄位{col_index + 1}"
        else:
            column_mapping[col] = original_col
    return column_mapping


def get_date_column(df: pd.DataFrame) -> str | None:
    mapping = get_column_mapping(df)
    for col, friendly in mapping.items():
        if friendly == "時間":
            return col
    return None


def format_course_data(df: pd.DataFrame, has_permission: bool) -> str:
    if df is None or df.empty:
        return "課程資料無法載入或為空"

    formatted_content = []
    column_mapping = get_column_mapping(df)

    for index, row in df.iterrows():
        course_info = []
        for col in df.columns:
            value = row[col]
            friendly_col_name = column_mapping.get(col, str(col))
            has_value = pd.notna(value) and str(value).strip()

            if has_value:
                if not has_permission and friendly_col_name in MEMBER_ONLY_FIELDS:
                    continue
                course_info.append(f"{friendly_col_name}: {value}")
            elif has_permission and friendly_col_name in MEMBER_ONLY_FIELDS:
                course_info.append(f"{friendly_col_name}: (尚未上傳)")

        if course_info:
            course_content = f"=== 課程記錄 {index + 1} ===\n" + "\n".join(course_info)
            formatted_content.append(course_content)

    return "\n\n".join(formatted_content)

