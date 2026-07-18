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
import os
import time
from datetime import datetime, timedelta
from typing import Tuple

import pandas as pd
import requests

from ian.config import CACHE_DIR, TZ_TPE
from ian.domain.courses import (
    MEMBER_ONLY_FIELDS,
    format_course_data,
    get_date_column,
    normalize_date,
    parse_dates_from_query,
)
from ian.utils.logging import elapsed_ms, log_event


course_data = None
last_course_update = None
course_update_interval = 0.5 * 60 * 60

COURSE_CACHE_FILE = str(CACHE_DIR / "course_data.csv")
COURSE_CACHE_TIMESTAMP_FILE = str(CACHE_DIR / "course_data_timestamp.txt")


def _get_cache_timestamp() -> float:
    try:
        if os.path.exists(COURSE_CACHE_TIMESTAMP_FILE):
            with open(COURSE_CACHE_TIMESTAMP_FILE, "r") as f:
                return float(f.read().strip())
    except (ValueError, IOError):
        pass
    return 0


def _save_cache_timestamp(timestamp: float):
    os.makedirs(str(CACHE_DIR), exist_ok=True)
    with open(COURSE_CACHE_TIMESTAMP_FILE, "w") as f:
        f.write(str(timestamp))


def _is_cache_valid() -> bool:
    if not os.path.exists(COURSE_CACHE_FILE):
        return False
    cache_timestamp = _get_cache_timestamp()
    current_time = time.time()
    return (current_time - cache_timestamp) < course_update_interval


def _load_from_cache() -> pd.DataFrame:
    global course_data, last_course_update
    try:
        df = pd.read_csv(COURSE_CACHE_FILE)
        course_data = df
        last_course_update = _get_cache_timestamp()
        log_event(
            "cache_loaded",
            "course_catalog",
            status="success",
            record_count=len(df),
        )
        return df
    except Exception as e:
        log_event(
            "cache_failed",
            "course_catalog",
            level="warning",
            status="failure",
            operation="load",
            error=e,
        )
        return None


def _save_to_cache(df: pd.DataFrame, timestamp: float):
    try:
        os.makedirs(str(CACHE_DIR), exist_ok=True)
        df.to_csv(COURSE_CACHE_FILE, index=False, encoding="utf-8")
        _save_cache_timestamp(timestamp)
        log_event("cache_saved", "course_catalog", status="success")
    except Exception as e:
        log_event(
            "cache_failed",
            "course_catalog",
            level="warning",
            status="failure",
            operation="save",
            error=e,
        )


def _fetch_from_url(url: str, max_retries: int = 3) -> pd.DataFrame:
    for attempt in range(max_retries):
        attempt_number = attempt + 1
        started_at = time.monotonic()
        try:
            log_event(
                "external_fetch_started",
                "course_catalog",
                status="started",
                source="course_data",
                attempt=attempt_number,
                max_attempts=max_retries,
            )
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            response.encoding = "utf-8"
            df = pd.read_csv(io.StringIO(response.text))

            if any(r"\x" in str(col) for col in df.columns):
                log_event(
                    "encoding_repair_started",
                    "course_catalog",
                    status="started",
                    source="course_data",
                )
                try:
                    response_bytes = requests.get(url, headers=headers, timeout=30).content
                    for encoding in ["utf-8", "utf-8-sig", "big5", "gb2312"]:
                        try:
                            decoded_text = response_bytes.decode(encoding)
                            df = pd.read_csv(io.StringIO(decoded_text))
                            if not any(r"\x" in str(col) for col in df.columns):
                                log_event(
                                    "encoding_repair_completed",
                                    "course_catalog",
                                    status="success",
                                    encoding=encoding,
                                )
                                break
                        except (UnicodeDecodeError, UnicodeError):
                            continue
                    else:
                        log_event(
                            "encoding_repair_failed",
                            "course_catalog",
                            level="warning",
                            status="failure",
                            reason="unsupported_encoding",
                        )
                except Exception as e:
                    log_event(
                        "encoding_repair_failed",
                        "course_catalog",
                        level="warning",
                        status="failure",
                        error=e,
                    )

            log_event(
                "external_fetch_completed",
                "course_catalog",
                status="success",
                duration_ms=elapsed_ms(started_at),
                source="course_data",
                attempt=attempt_number,
                record_count=len(df),
            )
            return df
        except requests.exceptions.RequestException as e:
            _log_fetch_failure(started_at, attempt_number, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
        except pd.errors.EmptyDataError as e:
            _log_fetch_failure(started_at, attempt_number, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
        except pd.errors.ParserError as e:
            _log_fetch_failure(started_at, attempt_number, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
        except Exception as e:
            _log_fetch_failure(started_at, attempt_number, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep(2**attempt)

    return None


def _log_fetch_failure(
    started_at: float,
    attempt: int,
    max_attempts: int,
    error: Exception,
) -> None:
    log_event(
        "external_fetch_failure",
        "course_catalog",
        level="warning",
        status="retrying" if attempt < max_attempts else "failure",
        duration_ms=elapsed_ms(started_at),
        source="course_data",
        attempt=attempt,
        max_attempts=max_attempts,
        error=error,
    )


def load_course_data_from_url(url: str, max_retries: int = 3) -> pd.DataFrame:
    global course_data, last_course_update

    if _is_cache_valid():
        return _load_from_cache()

    if not url:
        log_event(
            "configuration_invalid",
            "course_catalog",
            level="warning",
            status="missing",
            setting="course_data_url",
        )
        if os.path.exists(COURSE_CACHE_FILE):
            log_event(
                "cache_fallback",
                "course_catalog",
                level="warning",
                status="stale",
                reason="missing_configuration",
            )
            return _load_from_cache()
        return None

    df = _fetch_from_url(url, max_retries)

    if df is not None:
        current_time = time.time()
        course_data = df
        last_course_update = current_time
        _save_to_cache(df, current_time)
        return df

    if os.path.exists(COURSE_CACHE_FILE):
        log_event(
            "cache_fallback",
            "course_catalog",
            level="warning",
            status="stale",
            reason="external_fetch_failed",
        )
        return _load_from_cache()

    return None


def get_upcoming_courses(has_permission: bool, weeks: int = 2) -> str:
    if course_data is None or course_data.empty:
        return ""
    date_col = get_date_column(course_data)
    if date_col is None:
        return ""
    now = datetime.now(TZ_TPE)
    today_str = normalize_date(now.year, now.month, now.day)
    end = now + timedelta(weeks=weeks)
    end_str = normalize_date(end.year, end.month, end.day)
    matching = []
    for idx, row in course_data.iterrows():
        d = str(row.get(date_col, "")).strip()
        if today_str <= d <= end_str:
            matching.append(idx)
    if not matching:
        return ""
    matched_data = course_data.iloc[matching]
    formatted = format_course_data(matched_data, has_permission)
    return f"近期課程（未來 {weeks} 週），共 {len(matching)} 筆：\n\n{formatted}"


def search_course_data_by_query(query: str, has_permission: bool) -> Tuple[bool, str]:
    if course_data is None or course_data.empty:
        return False, "課程資料尚未載入或為空，請稍後再試"

    try:
        date_col = get_date_column(course_data)
        parsed_dates = parse_dates_from_query(query)

        if parsed_dates and date_col is not None:
            matching_rows = []
            if len(parsed_dates) == 1:
                target = parsed_dates[0]
                for idx, row in course_data.iterrows():
                    if str(row.get(date_col, "")).strip() == target:
                        matching_rows.append(idx)
            else:
                start, end = sorted(parsed_dates[:2])
                for idx, row in course_data.iterrows():
                    d = str(row.get(date_col, "")).strip()
                    if start <= d <= end:
                        matching_rows.append(idx)
            if matching_rows:
                matched_data = course_data.iloc[matching_rows]
                formatted_data = format_course_data(matched_data, has_permission)
                return True, f"找到 {len(matching_rows)} 筆課程資料：\n\n{formatted_data}"

        query_lower = query.lower()
        matching_rows = []
        for index, row in course_data.iterrows():
            row_text = " ".join([str(val) for val in row.values if pd.notna(val)]).lower()
            if query_lower in row_text:
                matching_rows.append(index)

        if matching_rows:
            matched_data = course_data.iloc[matching_rows]
            formatted_data = format_course_data(matched_data, has_permission)
            return True, f"找到 {len(matching_rows)} 筆包含 '{query}' 的課程資料：\n\n{formatted_data}"
        return False, ""
    except Exception as e:
        return False, f"搜尋課程資料時發生錯誤: {str(e)}"


def get_all_course_data(has_permission: bool) -> str:
    if course_data is None or course_data.empty:
        return "目前沒有任何課程資料"

    formatted_data = format_course_data(course_data, has_permission)
    return f"所有課程資料，共 {len(course_data)} 筆：\n\n{formatted_data}"


def get_permission_notice(has_permission: bool) -> str:
    if not has_permission:
        return f"\n\n💡 注意：目前無法獲取您的社員狀態，因此無法取得{', '.join(MEMBER_ONLY_FIELDS)}等內容。"
    return ""
