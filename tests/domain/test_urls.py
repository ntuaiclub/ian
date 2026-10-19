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


def test_validate_urls_rejects_uppercase_schemes():
    cleaned = validate_urls_in_response(
        "講義：HTTPS://unapproved.example/slides 與 Http://other.example/a",
        tool_results=[],
    )
    assert "HTTPS://unapproved.example/slides" not in cleaned
    assert "Http://other.example/a" not in cleaned
    assert cleaned.count("(連結讀取錯誤，請重新索取)") == 2


def test_validate_urls_allows_uppercase_scheme_when_approved():
    cleaned = validate_urls_in_response(
        "講義：HTTPS://docs.example/slides",
        tool_results=["鏡像：https://docs.example/slides"],
    )
    assert cleaned == "講義：HTTPS://docs.example/slides"


def test_validate_urls_does_not_corrupt_approved_nested_url():
    approved = "https://cdn.example/render?src=https://images.example/pic.png"
    response = f"圖片：{approved}\n其他：https://images.example/pic.png"

    cleaned = validate_urls_in_response(response, tool_results=[approved])

    assert approved in cleaned
    assert cleaned.endswith("(連結讀取錯誤，請重新索取)")
    assert "https://images.example/pic.png" not in cleaned.split("\n", 1)[1]
