import json
import threading
from pathlib import Path

from ian.domain.members import PLATFORM_FIELD_MAP, normalize_email


class MemberCache:
    """Local JSON-backed member cache with synchronized in-memory access."""

    def __init__(self, path: Path, members: list[dict] | None = None):
        self.path = path
        self._members = members or []
        self._lock = threading.Lock()

    def load(self) -> list[dict] | None:
        if not self.path.exists():
            return None

        members = json.loads(self.path.read_text(encoding="utf-8"))
        self.replace_all(members)
        return members

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.all(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def replace_all(self, members: list[dict]) -> None:
        with self._lock:
            self._members = members

    def all(self) -> list[dict]:
        with self._lock:
            return list(self._members)

    def find_by_platform(self, platform: str, account_id: str) -> dict | None:
        field = PLATFORM_FIELD_MAP.get(platform)
        if not field or not account_id:
            return None

        normalized_account_id = account_id.strip()
        with self._lock:
            for member in self._members:
                stored_id = str(member.get(field, "")).strip()
                if stored_id and stored_id == normalized_account_id:
                    return member
        return None

    def find_by_email(self, email: str) -> dict | None:
        normalized = normalize_email(email)
        with self._lock:
            for member in self._members:
                stored_email = normalize_email(member.get("email", ""))
                if stored_email and stored_email == normalized:
                    return member
        return None

    def update_field(self, email: str, field: str, value: str) -> bool:
        normalized = normalize_email(email)
        with self._lock:
            for member in self._members:
                if normalize_email(member.get("email", "")) == normalized:
                    member[field] = value
                    return True
        return False
