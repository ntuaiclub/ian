# SPDX-FileCopyrightText: 2026 NTU AI Club
# SPDX-License-Identifier: GPL-3.0-or-later

from ian.domain.urls import extract_urls, parse_no_response, validate_urls_in_response


def test_parse_no_response_supports_optional_emoji():
    assert parse_no_response("[NO_RESPONSE]") == (True, None)
    assert parse_no_response("[NO_RESPONSE:🔥]") == (True, "🔥")
    assert parse_no_response("一般回覆") == (False, None)


def test_extract_urls_strips_common_cjk_punctuation():
    text = "請看 https://example.com/a?b=1，或 https://ntuai.org/path。"
    assert extract_urls(text) == {"https://example.com/a?b=1", "https://ntuai.org/path"}


def test_validate_urls_replaces_unapproved_response_urls():
    response = "官方連結 https://linktr.ee/ntuai 與假連結 https://fake.example/path"
    cleaned = validate_urls_in_response(
        response,
        tool_results=["講義在 https://docs.example/slides"],
        prompt_text="NTUAI Links：https://linktr.ee/ntuai",
    )
    assert "https://linktr.ee/ntuai" in cleaned
    assert "https://fake.example/path" not in cleaned
    assert "(連結讀取錯誤，請重新索取)" in cleaned
