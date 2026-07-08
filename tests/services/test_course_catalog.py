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

import time
from datetime import datetime

import pandas as pd

from ian.config import TZ_TPE
from ian.services import course_catalog


def setup_function():
    course_catalog.course_data = None
    course_catalog.last_course_update = None


def _course_fixture():
    return pd.DataFrame(
        [
            {
                "時間": "2026/03/07",
                "社課主題/活動名稱": "生成式 AI",
                "線上連結": "https://meet.example/genai",
                "課程講義": "https://slides.example/genai",
            },
            {
                "時間": "2026/03/14",
                "社課主題/活動名稱": "資料科學",
                "線上連結": "https://meet.example/data",
                "課程講義": "",
            },
            {
                "時間": "2026/04/04",
                "社課主題/活動名稱": "遠期活動",
                "線上連結": "https://meet.example/future",
                "課程講義": "",
            },
        ]
    )


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 3, 1, 12, 0, tzinfo=TZ_TPE)


def test_search_course_data_by_query_matches_normalized_date():
    course_catalog.course_data = pd.DataFrame(
        [
            {"時間": "2026/03/07", "社課主題/活動名稱": "生成式 AI"},
            {"時間": "2026/03/08", "社課主題/活動名稱": "資料科學"},
        ]
    )

    found, result = course_catalog.search_course_data_by_query("2026-3-7", has_permission=False)

    assert found
    assert "找到 1 筆課程資料" in result
    assert "生成式 AI" in result
    assert "資料科學" not in result


def test_search_course_data_by_query_matches_date_range_from_in_memory_fixture():
    course_catalog.course_data = _course_fixture()

    found, result = course_catalog.search_course_data_by_query(
        "2026/03/01 到 2026/03/31", has_permission=True
    )

    assert found
    assert "找到 2 筆課程資料" in result
    assert "生成式 AI" in result
    assert "資料科學" in result
    assert "遠期活動" not in result


def test_search_course_data_by_query_filters_member_only_fields_by_permission():
    course_catalog.course_data = _course_fixture()

    public_found, public_result = course_catalog.search_course_data_by_query(
        "生成式 AI", has_permission=False
    )
    member_found, member_result = course_catalog.search_course_data_by_query(
        "生成式 AI", has_permission=True
    )

    assert public_found
    assert member_found
    assert "社課主題/活動名稱: 生成式 AI" in public_result
    assert "線上連結:" not in public_result
    assert "課程講義:" not in public_result
    assert "線上連結: https://meet.example/genai" in member_result
    assert "課程講義: https://slides.example/genai" in member_result


def test_get_upcoming_courses_uses_in_memory_fixture_and_current_date(monkeypatch):
    course_catalog.course_data = _course_fixture()
    monkeypatch.setattr(course_catalog, "datetime", FixedDateTime)

    result = course_catalog.get_upcoming_courses(has_permission=False, weeks=2)

    assert "近期課程（未來 2 週），共 2 筆" in result
    assert "生成式 AI" in result
    assert "資料科學" in result
    assert "遠期活動" not in result
    assert "線上連結:" not in result


def test_load_course_data_uses_valid_cache(monkeypatch, tmp_path):
    cache_file = tmp_path / "course_data.csv"
    timestamp_file = tmp_path / "course_data_timestamp.txt"
    cache_file.write_text("時間,社課主題/活動名稱\n2026/03/07,生成式 AI\n", encoding="utf-8")
    timestamp_file.write_text(str(time.time()), encoding="utf-8")

    monkeypatch.setattr(course_catalog, "COURSE_CACHE_FILE", str(cache_file))
    monkeypatch.setattr(course_catalog, "COURSE_CACHE_TIMESTAMP_FILE", str(timestamp_file))

    df = course_catalog.load_course_data_from_url("")

    assert list(df["社課主題/活動名稱"]) == ["生成式 AI"]
    assert course_catalog.course_data is df
