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
URL_PATTERN = re.compile(r"https?://[^\s\)）\]」'>,，、。]+")


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

    for url in URL_PATTERN.findall(response):
        url_norm = url.rstrip("/")
        if not any(
            url_norm.startswith(allowed.rstrip("/"))
            or allowed.rstrip("/").startswith(url_norm)
            for allowed in allowed_urls
        ):
            response = response.replace(url, URL_PLACEHOLDER)

    return response
