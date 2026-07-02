import json
import os
import sys
import time
import requests
import io
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import pandas as pd

TZ_TPE = timezone(timedelta(hours=8))

MEMBER_DB_FILE = Path(__file__).parent / "data" / "member_db.json"
COURSE_DATA_URL = os.environ.get("COURSE_DATA_URL", "")

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")

LOG_CHANNEL_ID = os.environ.get("DISCORD_LOG_CHANNEL_ID", "")

REMINDER_HOUR = 19
REMINDER_MINUTE = 0

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def load_members() -> list[dict]:
    data = json.loads(MEMBER_DB_FILE.read_text(encoding="utf-8"))
    return data


def get_valid_bound_members(members: list[dict]) -> list[dict]:
    now = datetime.now(TZ_TPE)
    result = []
    for m in members:
        vd = m.get("valid_date", "")
        if not vd:
            continue
        try:
            valid_date = datetime.fromisoformat(vd.replace("Z", "+00:00"))
            if now > valid_date:
                continue
        except (ValueError, TypeError):
            continue

        subscribe = str(m.get("subscribe", "")).strip().lower()
        if not subscribe:
            continue

        subscribed_platforms = [p.strip() for p in subscribe.split(",") if p.strip()]

        discord_id = str(m.get("discord_acc_id", "")).strip()
        has_discord = bool(discord_id and discord_id != "0") and "discord" in subscribed_platforms

        if has_discord:
            result.append({
                "name": m.get("name", ""),
                "email": m.get("email", ""),
                "tier": m.get("Tier", ""),
                "discord_id": discord_id,
            })
    return result


def fetch_course_data() -> pd.DataFrame:
    if not COURSE_DATA_URL:
        raise RuntimeError("COURSE_DATA_URL is not configured")

    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(COURSE_DATA_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return pd.read_csv(io.StringIO(resp.text))


def _clean(val) -> str:
    s = str(val).strip() if pd.notna(val) else ""
    return "" if s.lower() in ("nan", "-", "無") else s


def find_events_on_date(df: pd.DataFrame, target_date: str) -> list[dict]:
    events = []
    for _, row in df.iterrows():
        event_date = str(row.get("時間", "")).strip()
        if event_date == target_date:
            events.append({
                "date": event_date,
                "weekday": _clean(row.get("星期")),
                "time": _clean(row.get("活動時間")),
                "venue": _clean(row.get("場地")),
                "title": _clean(row.get("社課主題 / 活動名稱")),
                "speaker": _clean(row.get("講者")),
                "outline": _clean(row.get("課程大綱")),
                "target": _clean(row.get("課程對象")),
                "livestream": _clean(row.get("是否直播")),
                "recording": _clean(row.get("是否錄影")),
                "online_link": _clean(row.get("線上連結")),
                "slides": _clean(row.get("課程講義")),
            })
    return events

def format_reminder_message(events: list[dict]) -> str:
    multi = len(events) > 1
    lines = ["Hi! 明天 NTUAI 有以下活動："]

    for i, ev in enumerate(events, 1):
        lines.append("")
        header = f"{'=' * 30}"
        if multi:
            header = f"{'=' * 3} [{i}] {ev['title']} {'=' * 3}"
        else:
            header = f"{'=' * 3} {ev['title']} {'=' * 3}"
        lines.append(header)

        lines.append(f"日期: {ev['date']} {ev['weekday']}")
        if ev["time"]:
            lines.append(f"時間: {ev['time']}")
        if ev["venue"]:
            lines.append(f"地點: {ev['venue']}")
        if ev["speaker"]:
            lines.append(f"講者: {ev['speaker']}")
        if ev["target"]:
            lines.append(f"對象: {ev['target']}")

        flags = []
        if ev["livestream"] == "Y":
            flags.append("線上直播")
        if ev["recording"] == "Y":
            flags.append("提供錄影")
        if flags:
            lines.append(f"備註: {' / '.join(flags)}")

        if ev["outline"]:
            lines.append(f"\n課程大綱:\n{ev['outline']}")

        if ev["online_link"]:
            lines.append(f"\n線上連結: {ev['online_link']}")
        if ev["slides"]:
            lines.append(f"講義: {ev['slides']}")
    return "\n".join(lines)

def send_discord_dm(user_id: str, text: str) -> bool:
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    r = requests.post(
        "https://discord.com/api/v10/users/@me/channels",
        headers=headers,
        json={"recipient_id": user_id},
        timeout=10,
    )
    if r.status_code != 200:
        eprint(f"  [Discord] Failed to create DM channel for {user_id}: {r.text}")
        return False

    dm_channel_id = r.json()["id"]

    r2 = requests.post(
        f"https://discord.com/api/v10/channels/{dm_channel_id}/messages",
        headers=headers,
        json={"content": text},
        timeout=10,
    )
    if r2.status_code != 200:
        eprint(f"  [Discord] Failed to send message to {user_id}: {r2.text}")
        return False
    return True

def send_log(message: str):
    if not DISCORD_BOT_TOKEN or not LOG_CHANNEL_ID:
        return
    try:
        url = f"https://discord.com/api/v10/channels/{LOG_CHANNEL_ID}/messages"
        headers = {
            "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
            "Content-Type": "application/json",
        }
        requests.post(url, headers=headers, json={"content": message}, timeout=10)
    except Exception:
        pass

def run_once(target_date: str | None = None, dry: bool = False):
    now = datetime.now(TZ_TPE)
    eprint(f"[Reminder] Started at {now.strftime('%Y-%m-%d %H:%M:%S')} UTC+8")

    if target_date is None:
        tomorrow = now + timedelta(days=1)
        target_date = tomorrow.strftime("%Y/%m/%d")

    eprint(f"[Reminder] Checking events for: {target_date}")

    try:
        df = fetch_course_data()
        eprint(f"[Reminder] Loaded {len(df)} events from Google Sheets")
    except Exception as e:
        eprint(f"[Reminder] Failed to fetch course data: {e}")
        send_log(f"```\n[REMINDER] FAILED to fetch course data: {e}\n```")
        return

    events = find_events_on_date(df, target_date)
    if not events:
        eprint(f"[Reminder] No events on {target_date}, done.")
        return

    eprint(f"[Reminder] Found {len(events)} event(s) on {target_date}:")
    for ev in events:
        eprint(f"  - {ev['title']} ({ev['time']})")

    message = format_reminder_message(events)
    eprint(f"\n[Reminder] Message:\n{message}\n")

    if dry:
        eprint("[Reminder] DRY RUN — no messages sent.")
        members = load_members()
        bound = get_valid_bound_members(members)
        eprint(f"[Reminder] Would notify {len(bound)} member(s):")
        for m in bound:
            eprint(f"  - {m['name']} (Discord)")
        return

    members = load_members()
    bound = get_valid_bound_members(members)
    eprint(f"[Reminder] Notifying {len(bound)} member(s)...")

    discord_ok, discord_fail = 0, 0

    for m in bound:
        name = m["name"]
        email = m.get("email", "")

        personal_message = message
        if name and email:
            checkin_url = f"https://watsonshih.github.io/QuickRecord/user.html?name={quote(name)}&id={quote(email)}"
            personal_message += f"\n\n簽到碼連結：{checkin_url}"

        if m["discord_id"]:
            eprint(f"  Sending Discord DM to {name}...")
            if send_discord_dm(m["discord_id"], personal_message):
                discord_ok += 1
                eprint(f"  [Discord] {name} OK")
            else:
                discord_fail += 1
            time.sleep(0.5)

    event_titles = ", ".join(ev["title"] for ev in events)
    summary = (
        f"```\n"
        f"[REMINDER] {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Events on {target_date}: {event_titles}\n"
        f"Discord: {discord_ok} sent, {discord_fail} failed\n"
        f"Total members notified: {discord_ok}\n"
        f"```"
    )
    eprint(f"\n{summary}")
    send_log(summary)

def _seconds_until_next_run() -> float:
    now = datetime.now(TZ_TPE)
    target = now.replace(hour=REMINDER_HOUR, minute=REMINDER_MINUTE, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def daemon_loop():
    eprint("[Reminder] Daemon mode started")
    while True:
        wait = _seconds_until_next_run()
        next_run = datetime.now(TZ_TPE) + timedelta(seconds=wait)
        eprint(
            f"[Reminder] Next run in {wait:.0f}s "
            f"(at {next_run.strftime('%Y-%m-%d %H:%M:%S')} UTC+8)"
        )
        time.sleep(wait)
        try:
            run_once()
        except Exception as e:
            eprint(f"[Reminder] Error during run: {e}")
            send_log(f"```\n[REMINDER] ERROR: {e}\n```")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Daily event reminder")
    parser.add_argument("--dry", action="store_true", help="Dry run, no messages sent")
    parser.add_argument("--date", type=str, help="Check specific date (YYYY/MM/DD)")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon, trigger daily at 19:00 UTC+8")
    args = parser.parse_args()

    if args.daemon:
        daemon_loop()
    else:
        run_once(target_date=args.date, dry=args.dry)


if __name__ == "__main__":
    main()
