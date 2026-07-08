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

import pandas as pd

from ian.domain.courses import (
    MEMBER_ONLY_FIELDS,
    clean_value,
    format_course_data,
    get_column_mapping,
    normalize_date,
    parse_dates_from_query,
)


def test_parse_dates_from_query_normalizes_full_dates():
    assert parse_dates_from_query("請查 2026-3-7 的社課") == ["2026/03/07"]
    assert normalize_date(2026, 3, 7) == "2026/03/07"


def test_parse_dates_from_query_uses_current_year_for_short_dates():
    assert parse_dates_from_query("3/7", current_year=2026) == ["2026/03/07"]
    assert parse_dates_from_query("03-07", current_year=2026) == ["2026/03/07"]


def test_clean_value_removes_empty_and_placeholder_values():
    assert clean_value(float("nan")) == ""
    assert clean_value(" - ") == ""
    assert clean_value("無") == ""
    assert clean_value(" 生成式 AI ") == "生成式 AI"


def test_get_column_mapping_repairs_encoded_column_by_position():
    df = pd.DataFrame(columns=["\\xdead", "時間"])
    mapping = get_column_mapping(df)
    assert mapping["\\xdead"] == "週次"
    assert mapping["時間"] == "時間"


def test_format_course_data_hides_member_only_fields_for_non_members():
    df = pd.DataFrame(
        [
            {
                "時間": "2026/03/07",
                "社課主題/活動名稱": "生成式 AI",
                "線上連結": "https://meet.example",
                "課程講義": "",
            }
        ]
    )

    public_text = format_course_data(df, has_permission=False)
    member_text = format_course_data(df, has_permission=True)

    assert "生成式 AI" in public_text
    assert all(field not in public_text for field in MEMBER_ONLY_FIELDS)
    assert "線上連結: https://meet.example" in member_text
    assert "課程講義: (尚未上傳)" in member_text


def test_format_course_data_cleans_empty_and_placeholder_values():
    df = pd.DataFrame(
        [
            {
                "時間": "2026/03/07",
                "社課主題/活動名稱": "生成式 AI",
                "場地": "-",
                "講者": "無",
                "課程講義": "-",
            }
        ]
    )

    text = format_course_data(df, has_permission=True)

    assert "社課主題/活動名稱: 生成式 AI" in text
    assert "場地:" not in text
    assert "講者:" not in text
    assert "課程講義: (尚未上傳)" in text
