from datetime import datetime, timedelta

import pandas as pd

from ian.config import TZ_TPE
from ian.domain.courses import clean_value
from ian.domain.members import is_valid_member, parse_subscribe_platforms


REMINDER_HOUR = 19
REMINDER_MINUTE = 0


def get_valid_bound_members(members: list[dict], now: datetime | None = None) -> list[dict]:
    result = []
    for member in members:
        if not is_valid_member(member, now=now):
            continue

        subscribed_platforms = parse_subscribe_platforms(str(member.get("subscribe", "")))
        discord_id = str(member.get("discord_acc_id", "")).strip()
        has_discord = bool(discord_id and discord_id != "0") and "discord" in subscribed_platforms

        if has_discord:
            result.append(
                {
                    "name": member.get("name", ""),
                    "email": member.get("email", ""),
                    "tier": member.get("Tier", ""),
                    "discord_id": discord_id,
                }
            )
    return result


def find_events_on_date(df: pd.DataFrame, target_date: str) -> list[dict]:
    events = []
    for _, row in df.iterrows():
        event_date = str(row.get("時間", "")).strip()
        if event_date == target_date:
            events.append(
                {
                    "date": event_date,
                    "weekday": clean_value(row.get("星期")),
                    "time": clean_value(row.get("活動時間")),
                    "venue": clean_value(row.get("場地")),
                    "title": clean_value(row.get("社課主題 / 活動名稱")),
                    "speaker": clean_value(row.get("講者")),
                    "outline": clean_value(row.get("課程大綱")),
                    "target": clean_value(row.get("課程對象")),
                    "livestream": clean_value(row.get("是否直播")),
                    "recording": clean_value(row.get("是否錄影")),
                    "online_link": clean_value(row.get("線上連結")),
                    "slides": clean_value(row.get("課程講義")),
                }
            )
    return events


def format_reminder_message(events: list[dict]) -> str:
    multi = len(events) > 1
    lines = ["Hi! 明天 NTUAI 有以下活動："]

    for i, event in enumerate(events, 1):
        lines.append("")
        header = f"{'=' * 30}"
        if multi:
            header = f"{'=' * 3} [{i}] {event['title']} {'=' * 3}"
        else:
            header = f"{'=' * 3} {event['title']} {'=' * 3}"
        lines.append(header)

        lines.append(f"日期: {event['date']} {event['weekday']}")
        if event["time"]:
            lines.append(f"時間: {event['time']}")
        if event["venue"]:
            lines.append(f"地點: {event['venue']}")
        if event["speaker"]:
            lines.append(f"講者: {event['speaker']}")
        if event["target"]:
            lines.append(f"對象: {event['target']}")

        flags = []
        if event["livestream"] == "Y":
            flags.append("線上直播")
        if event["recording"] == "Y":
            flags.append("提供錄影")
        if flags:
            lines.append(f"備註: {' / '.join(flags)}")

        if event["outline"]:
            lines.append(f"\n課程大綱:\n{event['outline']}")
        if event["online_link"]:
            lines.append(f"\n線上連結: {event['online_link']}")
        if event["slides"]:
            lines.append(f"講義: {event['slides']}")
    return "\n".join(lines)


def seconds_until_next_run(
    now: datetime | None = None,
    hour: int = REMINDER_HOUR,
    minute: int = REMINDER_MINUTE,
) -> float:
    current = now or datetime.now(TZ_TPE)
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if current >= target:
        target += timedelta(days=1)
    return (target - current).total_seconds()

