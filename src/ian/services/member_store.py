import json
import sys
import threading
import time
import requests
from datetime import datetime, timedelta
from typing import Optional

from ian.config import MEMBER_API_KEY, MEMBER_API_URL, MEMBER_DB_FILE, TZ_TPE
from ian.domain.members import (
    PERSONAL_PROMPT_MAX_LEN,
    PLATFORM_FIELD_MAP,
    SUBSCRIBE_PLATFORM_FIELD as _SUBSCRIBE_PLATFORM_FIELD,
    VALID_SUBSCRIBE_PLATFORMS,
    get_role_from_tier,
    is_valid_member,
    normalize_email,
)

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# In-memory member data (list of dicts)
_member_data: list[dict] = []
_member_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Sync from API
# ---------------------------------------------------------------------------
def sync_member_data() -> bool:
    """Fetch latest member data from API and save to local file."""
    try:
        if not MEMBER_API_URL or not MEMBER_API_KEY:
            eprint("[MemberDB] MEMBER_API_URL or MEMBER_API_KEY is not configured")
            return False

        eprint("[MemberDB] Syncing member data from API...")
        resp = requests.get(
            MEMBER_API_URL,
            params={"api_key": MEMBER_API_KEY},
            timeout=30,
            allow_redirects=True,
        )
        resp.raise_for_status()
        payload = resp.json()

        if payload.get("status") != "success":
            eprint(f"[MemberDB] API returned non-success: {payload.get('status')}")
            return False

        data = payload.get("data", [])
        if not data:
            eprint("[MemberDB] API returned empty data")
            return False

        # Save to local file
        MEMBER_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        MEMBER_DB_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Update in-memory cache
        with _member_lock:
            global _member_data
            _member_data = data

        eprint(f"[MemberDB] Synced {len(data)} members successfully")
        return True
    except Exception as e:
        eprint(f"[MemberDB] Sync failed: {e}")
        return False


def load_member_db() -> bool:
    """Load member data from local file into memory."""
    global _member_data
    try:
        if not MEMBER_DB_FILE.exists():
            eprint("[MemberDB] Local DB file not found, attempting sync...")
            return sync_member_data()

        data = json.loads(MEMBER_DB_FILE.read_text(encoding="utf-8"))
        with _member_lock:
            _member_data = data
        eprint(f"[MemberDB] Loaded {len(data)} members from local file")
        return True
    except Exception as e:
        eprint(f"[MemberDB] Failed to load local DB: {e}")
        return False


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------
def lookup_member_by_platform(platform: str, account_id: str) -> Optional[dict]:
    """Find a member by their platform account ID.

    Returns the member dict if found, None otherwise.
    """
    field = PLATFORM_FIELD_MAP.get(platform)
    if not field or not account_id:
        return None

    with _member_lock:
        for member in _member_data:
            stored_id = str(member.get(field, "")).strip()
            if stored_id and stored_id == account_id.strip():
                return member
    return None


def get_member_name(platform: str, account_id: str) -> Optional[str]:
    """Return the member's name (id field) by platform account ID, or None if not found."""
    member = lookup_member_by_platform(platform, account_id)
    if not member:
        load_member_db()
        member = lookup_member_by_platform(platform, account_id)
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
    member = lookup_member_by_platform(platform, account_id)
    if not member:
        # Reload from file — another process may have updated it
        load_member_db()
        member = lookup_member_by_platform(platform, account_id)
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
    normalized = normalize_email(email)
    with _member_lock:
        for member in _member_data:
            stored_email = normalize_email(member.get("email", ""))
            if stored_email and stored_email == normalized:
                return member
    return None


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
    with _member_lock:
        for m in _member_data:
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
        payload = {
            "api_key": MEMBER_API_KEY,
            "email": member.get("email", ""),  # Use original email from DB
            field: account_id,
        }
        resp = requests.post(
            MEMBER_API_URL,
            json=payload,
            timeout=30,
            allow_redirects=True,
        )
        resp.raise_for_status()
        result = resp.json()

        if result.get("status") != "success":
            return {
                "success": False,
                "message": f"API 更新失敗: {result.get('message', '未知錯誤')}",
            }
    except Exception as e:
        return {"success": False, "message": f"綁定時發生錯誤: {e}"}

    # 3. Update local cache
    with _member_lock:
        for m in _member_data:
            if normalize_email(m.get("email", "")) == normalize_email(email):
                m[field] = account_id
                break

    # Save updated data to local file
    try:
        MEMBER_DB_FILE.write_text(
            json.dumps(_member_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        eprint(f"[MemberDB] Failed to save local DB after binding: {e}")

    name = member.get("id", "")
    role = get_role_from_tier(member.get("Tier", ""))

    # Build bound platforms summary (use updated member dict)
    with _member_lock:
        updated = next(
            (m for m in _member_data if normalize_email(m.get("email", "")) == normalize_email(email)),
            member,
        )
    bound_platforms = [p for p, f in PLATFORM_FIELD_MAP.items() if str(updated.get(f, "")).strip()]
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
        payload = {
            "api_key": MEMBER_API_KEY,
            "email": email,
            field: value,
        }
        resp = requests.post(
            MEMBER_API_URL,
            json=payload,
            timeout=30,
            allow_redirects=True,
        )
        resp.raise_for_status()
        result = resp.json()

        if result.get("status") != "success":
            return {
                "success": False,
                "message": f"API 更新失敗: {result.get('message', '未知錯誤')}",
            }
    except Exception as e:
        return {"success": False, "message": f"更新時發生錯誤: {e}"}

    # Update local cache
    with _member_lock:
        for m in _member_data:
            if normalize_email(m.get("email", "")) == normalize_email(email):
                m[field] = value
                break

    try:
        MEMBER_DB_FILE.write_text(
            json.dumps(_member_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        eprint(f"[MemberDB] Failed to save local DB after update: {e}")

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
    member = lookup_member_by_platform(platform, account_id)
    if not member:
        load_member_db()
        member = lookup_member_by_platform(platform, account_id)
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

    raw_platforms = [p.strip().lower() for p in subscribe_str.split(",") if p.strip()]
    invalid = [p for p in raw_platforms if p not in VALID_SUBSCRIBE_PLATFORMS]
    if invalid:
        return {
            "success": False,
            "message": f"不支援的平台: {', '.join(invalid)}。目前僅支援: {', '.join(sorted(VALID_SUBSCRIBE_PLATFORMS))}",
        }

    # Deduplicate
    platforms = sorted(set(raw_platforms))

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
    member = lookup_member_by_platform(platform, account_id)
    if not member:
        load_member_db()
        member = lookup_member_by_platform(platform, account_id)
    if not member:
        return {"success": False, "message": "找不到您的社員資料，無法更新個人備註。"}

    text = prompt_text.strip()
    if len(text) > PERSONAL_PROMPT_MAX_LEN:
        text = text[:PERSONAL_PROMPT_MAX_LEN]

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
                eprint(
                    f"[MemberDB] Next sync in {wait_seconds:.0f}s "
                    f"(at {tomorrow.strftime('%Y-%m-%d %H:%M:%S')} UTC+8)"
                )
                time.sleep(wait_seconds)
                sync_member_data()
            except Exception as e:
                eprint(f"[MemberDB] Scheduler error: {e}")
                time.sleep(3600)  # Retry in 1 hour on error

    thread = threading.Thread(target=_scheduler_loop, daemon=True)
    thread.start()
    eprint("[MemberDB] Daily sync scheduler started")


# ---------------------------------------------------------------------------
# Initialization — load on import
# ---------------------------------------------------------------------------
def init():
    """Initialize member DB: load from local file, sync from API, start scheduler."""
    loaded = load_member_db()
    if not loaded:
        eprint("[MemberDB] Initial load failed, will retry on first lookup")
    # Always try to sync fresh data in background on startup
    threading.Thread(target=sync_member_data, daemon=True).start()
    start_daily_sync()
