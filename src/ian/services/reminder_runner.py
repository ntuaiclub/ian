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

import json
import io
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pandas as pd
import requests

from ian.config import COURSE_DATA_URL, MEMBER_DB_FILE
from ian.domain.reminders import (
    find_events_on_date,
    format_reminder_message,
    get_valid_bound_members,
    seconds_until_next_run,
)
from ian.services.notifications import send_discord_dm, send_log
from ian.utils.console import eprint

TZ_TPE = timezone(timedelta(hours=8))

REMINDER_HOUR = 19
REMINDER_MINUTE = 0


def load_members() -> list[dict]:
    data = json.loads(MEMBER_DB_FILE.read_text(encoding="utf-8"))
    return data


def fetch_course_data() -> pd.DataFrame:
    if not COURSE_DATA_URL:
        raise RuntimeError("COURSE_DATA_URL is not configured")

    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(COURSE_DATA_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return pd.read_csv(io.StringIO(resp.text))


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

    try:
        members = load_members()
        bound = get_valid_bound_members(members)
    except Exception as e:
        eprint(f"[Reminder] Failed to load member data: {e}")
        send_log(f"```\n[REMINDER] FAILED to load member data: {e}\n```")
        return

    if dry:
        eprint("[Reminder] DRY RUN — no messages sent.")
        eprint(f"[Reminder] Would notify {len(bound)} member(s):")
        for m in bound:
            eprint(f"  - {m['name']} (Discord)")
        return

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
            try:
                if send_discord_dm(m["discord_id"], personal_message):
                    discord_ok += 1
                    eprint(f"  [Discord] {name} OK")
                else:
                    discord_fail += 1
            except Exception as e:
                discord_fail += 1
                eprint(f"  [Discord] {name} failed: {e}")
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

def daemon_loop():
    eprint("[Reminder] Daemon mode started")
    while True:
        wait = seconds_until_next_run(hour=REMINDER_HOUR, minute=REMINDER_MINUTE)
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
