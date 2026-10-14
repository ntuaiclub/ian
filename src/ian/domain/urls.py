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
from urllib.parse import urlsplit


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


def _effective_port(parts) -> int | None:
    if parts.port is not None:
        return parts.port
    scheme = (parts.scheme or "").lower()
    if scheme == "http":
        return 80
    if scheme == "https":
        return 443
    return None


def _normalize_path(path: str) -> str:
    if not path or path == "/":
        return ""
    return path.rstrip("/")


def _path_allows(allowed_path: str, response_path: str) -> bool:
    """True when response_path equals allowed_path or is a child segment."""
    allowed = _normalize_path(allowed_path)
    response = _normalize_path(response_path)
    if allowed == "":
        return True
    if response == allowed:
        return True
    return response.startswith(allowed + "/")


def _urls_share_allowance(response_url: str, allowed_url: str) -> bool:
    """Authority-aware allowance: same origin, path equal or nested either way.

    Replaces raw-string prefix matching, which accepted hosts like
    ``trusted.example.evil`` and userinfo tricks like ``trusted.example@evil``.
    """
    response = urlsplit(response_url)
    allowed = urlsplit(allowed_url)
    if not response.scheme or not response.hostname:
        return False
    if not allowed.scheme or not allowed.hostname:
        return False
    if response.scheme.lower() != allowed.scheme.lower():
        return False
    if response.hostname.lower() != allowed.hostname.lower():
        return False
    if _effective_port(response) != _effective_port(allowed):
        return False
    return _path_allows(allowed.path, response.path) or _path_allows(
        response.path, allowed.path
    )


def validate_urls_in_response(
    response: str,
    tool_results: list[str],
    prompt_text: str = "",
) -> str:
    allowed_urls = extract_urls(prompt_text)
    for result in tool_results:
        allowed_urls.update(extract_urls(result))

    for url in URL_PATTERN.findall(response):
        if not any(_urls_share_allowance(url, allowed) for allowed in allowed_urls):
            response = response.replace(url, URL_PLACEHOLDER)

    return response
