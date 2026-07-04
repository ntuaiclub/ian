import os
from datetime import timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

TZ_TPE = timezone(timedelta(hours=8))

def _env(name: str, default: str = "") -> str:
    return os.environ.get(name) or default


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value else default


MCP_HOST = _env("MCP_HOST", "0.0.0.0")
MCP_PORT = _env_int("MCP_PORT", 5191)

COURSE_DATA_URL = _env("COURSE_DATA_URL")
CACHE_DIR = PROJECT_ROOT / "cache"
DATA_DIR = PROJECT_ROOT / "data"

DISCORD_BOT_TOKEN = _env("DISCORD_BOT_TOKEN")
DISCORD_LOG_CHANNEL_ID = _env("DISCORD_LOG_CHANNEL_ID")
DISCORD_LOG_CHANNEL_ID_INT = _env_int("DISCORD_LOG_CHANNEL_ID", 0)
STAFF_NOTIFICATION_CHANNEL_ID = _env("STAFF_NOTIFICATION_CHANNEL_ID")

GOOGLE_API_KEY = _env("GOOGLE_API_KEY")

PAGE_ACCESS_TOKEN = _env("PAGE_ACCESS_TOKEN")
FB_VERIFY_TOKEN = _env("FB_VERIFY_TOKEN")

LINE_CHANNEL_ACCESS_TOKEN = _env("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = _env("LINE_CHANNEL_SECRET")

MEMBER_API_URL = _env("MEMBER_API_URL")
MEMBER_API_KEY = _env("MEMBER_API_KEY")
MEMBER_DB_FILE = DATA_DIR / "member_db.json"

ALLOWED_DISCORD_CHANNELS = [
    c.strip() for c in _env("DISCORD_ALLOWED_CHANNELS").split(",") if c.strip()
]
LINE_ALLOWED_GROUPS = [
    g.strip() for g in _env("LINE_ALLOWED_GROUPS").split(",") if g.strip()
]
ALLOWED_CHANNELS = ALLOWED_DISCORD_CHANNELS + LINE_ALLOWED_GROUPS
