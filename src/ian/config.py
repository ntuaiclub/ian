import os
from datetime import timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TZ_TPE = timezone(timedelta(hours=8))

MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "5191"))

COURSE_DATA_URL = os.environ.get("COURSE_DATA_URL", "")
CACHE_DIR = PROJECT_ROOT / "cache"
DATA_DIR = PROJECT_ROOT / "data"

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_LOG_CHANNEL_ID = os.environ.get("DISCORD_LOG_CHANNEL_ID", "")
STAFF_NOTIFICATION_CHANNEL_ID = os.environ.get("STAFF_NOTIFICATION_CHANNEL_ID", "")

MEMBER_API_URL = os.environ.get("MEMBER_API_URL", "")
MEMBER_API_KEY = os.environ.get("MEMBER_API_KEY", "")
MEMBER_DB_FILE = DATA_DIR / "member_db.json"

ALLOWED_DISCORD_CHANNELS = [
    c.strip() for c in os.environ.get("DISCORD_ALLOWED_CHANNELS", "").split(",") if c.strip()
]
LINE_ALLOWED_GROUPS = [
    g.strip() for g in os.environ.get("LINE_ALLOWED_GROUPS", "").split(",") if g.strip()
]
ALLOWED_CHANNELS = ALLOWED_DISCORD_CHANNELS + LINE_ALLOWED_GROUPS
