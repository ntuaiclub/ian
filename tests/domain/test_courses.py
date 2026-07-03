import pandas as pd

from ian.domain.courses import (
    MEMBER_ONLY_FIELDS,
    format_course_data,
    get_column_mapping,
    normalize_date,
    parse_dates_from_query,
)


def test_parse_dates_from_query_normalizes_full_dates():
    assert parse_dates_from_query("請查 2026-3-7 的社課") == ["2026/03/07"]
    assert normalize_date(2026, 3, 7) == "2026/03/07"


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
