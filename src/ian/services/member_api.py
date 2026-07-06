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

import requests


class MemberApiError(Exception):
    """Raised when the member API cannot complete a requested operation."""


def _require_config(api_url: str, api_key: str) -> None:
    if not api_url or not api_key:
        raise MemberApiError("MEMBER_API_URL or MEMBER_API_KEY is not configured")


def fetch_members(api_url: str, api_key: str) -> list[dict]:
    """Fetch member records from the remote member API."""
    _require_config(api_url, api_key)

    resp = requests.get(
        api_url,
        params={"api_key": api_key},
        timeout=30,
        allow_redirects=True,
    )
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("status") != "success":
        message = payload.get("message") or payload.get("status") or "unknown error"
        raise MemberApiError(str(message))

    data = payload.get("data", [])
    if not data:
        raise MemberApiError("empty data")

    return data


def update_member_fields(
    api_url: str,
    api_key: str,
    email: str,
    fields: dict[str, str],
) -> None:
    """Update one member record in the remote member API."""
    _require_config(api_url, api_key)

    payload = {
        "api_key": api_key,
        "email": email,
        **fields,
    }
    resp = requests.post(
        api_url,
        json=payload,
        timeout=30,
        allow_redirects=True,
    )
    resp.raise_for_status()
    result = resp.json()

    if result.get("status") != "success":
        message = result.get("message") or result.get("status") or "未知錯誤"
        raise MemberApiError(str(message))
