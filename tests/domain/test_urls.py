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


def test_validate_urls_rejects_hostname_prefix_phishing():
    """Regression for #133: a longer hostname that shares a string prefix with
    an allowed host must not be treated as allowed."""
    cleaned = validate_urls_in_response(
        "https://trusted.example.evil/phish",
        tool_results=["https://trusted.example"],
    )
    assert cleaned == "(連結讀取錯誤，請重新索取)"


def test_validate_urls_rejects_userinfo_host_spoof():
    """Regression for #133: userinfo before '@' must not count as the host."""
    cleaned = validate_urls_in_response(
        "https://trusted.example@evil.example/phish",
        tool_results=["https://trusted.example"],
    )
    assert cleaned == "(連結讀取錯誤，請重新索取)"


def test_validate_urls_allows_same_origin_subpath():
    cleaned = validate_urls_in_response(
        "詳見 https://cdn.example/docs/guide.html",
        tool_results=["https://cdn.example/docs"],
    )
    assert "https://cdn.example/docs/guide.html" in cleaned
    assert "(連結讀取錯誤，請重新索取)" not in cleaned


def test_validate_urls_allows_parent_of_approved_path():
    cleaned = validate_urls_in_response(
        "首頁 https://cdn.example/docs",
        tool_results=["https://cdn.example/docs/guide.html"],
    )
    assert "https://cdn.example/docs" in cleaned


def test_validate_urls_rejects_different_port():
    cleaned = validate_urls_in_response(
        "https://trusted.example:8443/path",
        tool_results=["https://trusted.example/path"],
    )
    assert cleaned == "(連結讀取錯誤，請重新索取)"
