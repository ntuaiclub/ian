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

import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from ian.config import MEMBER_API_KEY, MEMBER_API_URL, MEMBER_DB_FILE, TZ_TPE
from ian.domain.members import (
    PLATFORM_FIELD_MAP,
    SUBSCRIBE_PLATFORM_FIELD as _SUBSCRIBE_PLATFORM_FIELD,
    VALID_SUBSCRIBE_PLATFORMS,
    get_role_from_tier,
    invalid_subscribe_platforms,
    is_valid_member,
    normalize_personal_prompt,
    parse_subscribe_platforms,
)
from ian.services.member_api import MemberApiError, fetch_members, update_member_fields
from ian.services.member_cache import MemberCache
from ian.utils.logging import elapsed_ms, log_event


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_cache = MemberCache(MEMBER_DB_FILE)

# ---------------------------------------------------------------------------
# Sync from API
# ---------------------------------------------------------------------------
def sync_member_data() -> bool:
    """Fetch latest member data from API and save to local file."""
    started_at = time.monotonic()
    log_event(
        "job_started",
        "member_store",
        status="started",
        job="member_sync",
    )
    try:
        data = fetch_members(MEMBER_API_URL, MEMBER_API_KEY)
        _cache.replace_all(data)
        _cache.save()

        log_event(
            "job_completed",
            "member_store",
            status="success",
            duration_ms=elapsed_ms(started_at),
            job="member_sync",
            member_count=len(data),
        )
        return True
    except Exception as e:
        log_event(
            "job_failed",
            "member_store",
            level="error",
            status="error",
            duration_ms=elapsed_ms(started_at),
            job="member_sync",
            error=e,
        )
        return False


def load_member_db() -> bool:
    """Load member data from local file into memory."""
    try:
        data = _cache.load()
        if data is None:
            log_event(
                "operation_failed",
                "member_store",
                level="warning",
                status="fallback",
                operation="load_member_cache",
                reason="file_not_found",
            )
            return sync_member_data()
        log_event(
            "operation_completed",
            "member_store",
            status="success",
            operation="load_member_cache",
            member_count=len(data),
        )
        return True
    except Exception as e:
        log_event(
            "operation_failed",
            "member_store",
            level="error",
            status="error",
            operation="load_member_cache",
            error=e,
        )
        return False


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------
def lookup_member_by_platform(platform: str, account_id: str) -> Optional[dict]:
    """Find a member by their platform account ID.

    Returns the member dict if found, None otherwise.
    """
    return _cache.find_by_platform(platform, account_id)


def _lookup_member_with_reload(platform: str, account_id: str) -> Optional[dict]:
    """Find a member, reloading local data once if the in-memory cache misses."""
    member = lookup_member_by_platform(platform, account_id)
    if member:
        return member

    load_member_db()
    return lookup_member_by_platform(platform, account_id)


def get_member_name(platform: str, account_id: str) -> Optional[str]:
    """Return the member's name (id field) by platform account ID, or None if not found."""
    member = _lookup_member_with_reload(platform, account_id)
    if member:
        return member.get("id", "").strip() or None
    return None


def get_member_role(platform: str, account_id: str) -> str:
    """Get the role string for a user based on platform and account ID.

    Returns the appropriate role if the user is a valid member,
    or '非社員' if not found / expired.

    If not found in memory, reloads from local file in case another
    process (e.g. MCP server) updated it via bind_email.
    """
    member = _lookup_member_with_reload(platform, account_id)
    if not member:
        return "非社員"
    if not is_valid_member(member):
        return "非社員（已過期）"
    return get_role_from_tier(member.get("Tier", ""))


# ---------------------------------------------------------------------------
# Email binding
# ---------------------------------------------------------------------------
def find_member_by_email(email: str) -> Optional[dict]:
    """Find a member by email (case-insensitive on local part)."""
    return _cache.find_by_email(email)


def bind_email(email: str, platform: str, account_id: str) -> dict:
    """Bind a platform account to a member via email.

    Steps:
    1. Check email exists in local member DB
    2. POST to API to update the binding
    3. Update local cache

    Returns dict with 'success' (bool) and 'message' (str).
    """
    field = PLATFORM_FIELD_MAP.get(platform)
    if not field:
        return {"success": False, "message": f"不支援的平台: {platform}"}

    if not account_id:
        return {"success": False, "message": "無法取得您的帳號 ID"}

    # 1. Find member by email
    member = find_member_by_email(email)
    if not member:
        return {
            "success": False,
            "message": (
                f"找不到此 Email（{email}）對應的資料。"
                "可能是新社員尚未確認付款狀態、或是當初申請時提供了不同的 Email，"
                "請聯繫幹部協助查詢與更新。"
            ),
        }

    # Check if already bound to this account
    existing = str(member.get(field, "")).strip()
    if existing == account_id.strip():
        name = member.get("id", "")
        role = get_role_from_tier(member.get("Tier", ""))
        return {
            "success": True,
            "message": f"您的帳號已經綁定為{role}「{name}」，無需重複綁定。",
        }

    # Prevent re-binding: this email already has a different account bound
    if existing:
        return {
            "success": False,
            "message": (
                f"此 Email 的 {platform} 帳號已綁定，無法更換綁定。"
                "如需變更，請聯繫幹部協助處理。"
            ),
        }

    # Prevent re-binding: this account is already bound to a different email
    for m in _cache.all():
        stored_id = str(m.get(field, "")).strip()
        if stored_id and stored_id == account_id.strip():
            return {
                "success": False,
                "message": (
                    f"此 {platform} 帳號已綁定身分，無法一個帳號綁定多個身分。"
                    "如需變更，請聯繫幹部協助處理。"
                ),
            }

    # Check if valid
    if not is_valid_member(member):
        return {
            "success": False,
            "message": f"此 Email 對應的{get_role_from_tier(member.get('Tier', ''))}資格已過期，無法綁定。",
        }

    # 2. POST to API
    try:
        update_member_fields(
            MEMBER_API_URL,
            MEMBER_API_KEY,
            member.get("email", ""),
            {field: account_id},
        )
    except MemberApiError as e:
        return {"success": False, "message": f"API 更新失敗: {e}"}
    except Exception as e:
        return {"success": False, "message": f"綁定時發生錯誤: {e}"}

    # 3. Update local cache
    _cache.update_field(email, field, account_id)

    # Save updated data to local file
    try:
        _cache.save()
    except Exception as e:
        log_event(
            "operation_failed",
            "member_store",
            level="error",
            status="error",
            operation="save_member_cache",
            source="bind_email",
            error=e,
        )

    name = member.get("id", "")
    role = get_role_from_tier(member.get("Tier", ""))

    # Build bound platforms summary (use updated member dict)
    updated = _cache.find_by_email(email) or member
    bound_platforms = [
        p for p, f in PLATFORM_FIELD_MAP.items() if str(updated.get(f, "")).strip()
    ]
    bound_str = "、".join(bound_platforms) if bound_platforms else "無"

    return {
        "success": True,
        "message": f"綁定成功！已將您的 {platform} 帳號綁定為{role}「{name}」。目前已綁定的平台：{bound_str}。",
    }


# ---------------------------------------------------------------------------
# Generic field update helper
# ---------------------------------------------------------------------------
def _update_member_field(email: str, field: str, value: str) -> dict:
    """POST a single field update to the API and update local cache."""
    try:
        update_member_fields(
            MEMBER_API_URL,
            MEMBER_API_KEY,
            email,
            {field: value},
        )
    except MemberApiError as e:
        return {"success": False, "message": f"API 更新失敗: {e}"}
    except Exception as e:
        return {"success": False, "message": f"更新時發生錯誤: {e}"}

    # Update local cache
    _cache.update_field(email, field, value)

    try:
        _cache.save()
    except Exception as e:
        log_event(
            "operation_failed",
            "member_store",
            level="error",
            status="error",
            operation="save_member_cache",
            source="update_member_field",
            error=e,
        )

    return {"success": True, "message": "更新成功"}


# ---------------------------------------------------------------------------
# Subscribe management
# ---------------------------------------------------------------------------
def update_subscribe(platform: str, account_id: str, subscribe_str: str) -> dict:
    """Update a member's notification subscription platforms.

    Args:
        platform: The platform the user is currently on (Discord, FB, LINE).
        account_id: The user's account ID on that platform.
        subscribe_str: Comma-separated platforms to subscribe (e.g. "discord"),
                       or empty string to unsubscribe all.

    Returns dict with 'success' (bool) and 'message' (str).
    """
    member = _lookup_member_with_reload(platform, account_id)
    if not member:
        return {"success": False, "message": "找不到您的社員資料，請先透過 Email 綁定身分。"}

    if not is_valid_member(member):
        return {"success": False, "message": "您的社員資格已過期，無法設定訂閱。"}

    # Parse and validate platforms
    if not subscribe_str.strip():
        # Unsubscribe all
        result = _update_member_field(member.get("email", ""), "subscribe", "")
        if result["success"]:
            result["message"] = "已取消所有通知訂閱。"
        return result

    invalid = invalid_subscribe_platforms(subscribe_str)
    if invalid:
        return {
            "success": False,
            "message": f"不支援的平台: {', '.join(invalid)}。目前僅支援: {', '.join(sorted(VALID_SUBSCRIBE_PLATFORMS))}",
        }

    platforms = parse_subscribe_platforms(subscribe_str)

    # Check that the member has bound the requested platforms
    unbound = []
    for p in platforms:
        field = _SUBSCRIBE_PLATFORM_FIELD.get(p)
        if field:
            bound_id = str(member.get(field, "")).strip()
            if not bound_id or bound_id == "0":
                unbound.append(p)
    if unbound:
        return {
            "success": False,
            "message": f"您尚未綁定 {', '.join(unbound)} 帳號，請先綁定後再訂閱該平台的通知。",
        }

    value = ",".join(platforms)
    result = _update_member_field(member.get("email", ""), "subscribe", value)
    if result["success"]:
        result["message"] = f"訂閱設定已更新！您將在以下平台收到每日課程通知：{', '.join(platforms)}"
    return result


# ---------------------------------------------------------------------------
# Personal prompt management
# ---------------------------------------------------------------------------
def update_personal_prompt(platform: str, account_id: str, prompt_text: str) -> dict:
    """Update a member's personal prompt (personality/preference memo).

    Args:
        platform: The platform the user is currently on.
        account_id: The user's account ID on that platform.
        prompt_text: The personal prompt text (max 100 chars, will be truncated).

    Returns dict with 'success' (bool) and 'message' (str).
    """
    member = _lookup_member_with_reload(platform, account_id)
    if not member:
        return {"success": False, "message": "找不到您的社員資料，無法更新個人備註。"}

    text = normalize_personal_prompt(prompt_text)
    result = _update_member_field(member.get("email", ""), "personal_prompt", text)
    if result["success"]:
        result["message"] = "已更新使用者個性備註。"
    return result


# ---------------------------------------------------------------------------
# Daily sync scheduler
# ---------------------------------------------------------------------------
_scheduler_started = False


def start_daily_sync():
    """Start a background thread that syncs member data daily at midnight (UTC+8)."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    def _scheduler_loop():
        while True:
            try:
                now = datetime.now(TZ_TPE)
                # Calculate seconds until next midnight
                tomorrow = (now + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                wait_seconds = (tomorrow - now).total_seconds()
                log_event(
                    "job_scheduled",
                    "member_store",
                    status="scheduled",
                    job="member_sync",
                    wait_seconds=wait_seconds,
                    next_run=tomorrow.isoformat(),
                )
                time.sleep(wait_seconds)
                sync_member_data()
            except Exception as e:
                log_event(
                    "job_failed",
                    "member_store",
                    level="error",
                    status="error",
                    job="member_sync",
                    stage="scheduler_loop",
                    error=e,
                )
                time.sleep(3600)  # Retry in 1 hour on error

    thread = threading.Thread(target=_scheduler_loop, daemon=True)
    thread.start()
    log_event(
        "service_started",
        "member_store",
        status="running",
        service="member_sync_scheduler",
    )


# ---------------------------------------------------------------------------
# Initialization — load on import
# ---------------------------------------------------------------------------
def init():
    """Initialize member DB: load from local file, sync from API, start scheduler."""
    loaded = load_member_db()
    if not loaded:
        log_event(
            "operation_failed",
            "member_store",
            level="warning",
            status="retry_pending",
            operation="initialize_member_store",
            reason="initial_load_failed",
        )
    # Always try to sync fresh data in background on startup
    threading.Thread(target=sync_member_data, daemon=True).start()
    start_daily_sync()
