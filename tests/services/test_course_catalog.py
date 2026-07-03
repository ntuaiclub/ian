import time

import pandas as pd

from ian.services import course_catalog


def setup_function():
    course_catalog.course_data = None
    course_catalog.last_course_update = None


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
