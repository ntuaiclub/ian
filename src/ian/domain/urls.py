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

import re


URL_PLACEHOLDER = "(連結讀取錯誤，請重新索取)"
URL_PATTERN = re.compile(r"https?://[^\s\)）\]」'>,，、。]+", re.IGNORECASE)


def _normalize_scheme(url: str) -> str:
    """Lowercase the URI scheme only; path and host stay unchanged."""
    match = re.match(r"^(https?)://", url, flags=re.IGNORECASE)
    if not match:
        return url
    return f"{match.group(1).lower()}://{url[match.end() :]}"


def extract_urls(text: str) -> set[str]:
    return set(URL_PATTERN.findall(text or ""))


def parse_no_response(text: str) -> tuple[bool, str | None]:
    if "NO_RESPONSE" not in text:
        return False, None
    match = re.search(r"\[NO_RESPONSE(?::(.+?))?\]", text)
    if match:
        return True, match.group(1) or None
    return True, None


def validate_urls_in_response(
    response: str,
    tool_results: list[str],
    prompt_text: str = "",
) -> str:
    allowed_urls = extract_urls(prompt_text)
    for result in tool_results:
        allowed_urls.update(extract_urls(result))

    allowed_norms = {_normalize_scheme(url).rstrip("/") for url in allowed_urls}

    def replace_unapproved(match: re.Match[str]) -> str:
        url = match.group(0)
        url_norm = _normalize_scheme(url).rstrip("/")
        if not any(
            url_norm.startswith(allowed) or allowed.startswith(url_norm)
            for allowed in allowed_norms
        ):
            return URL_PLACEHOLDER
        return url

    return URL_PATTERN.sub(replace_unapproved, response)
