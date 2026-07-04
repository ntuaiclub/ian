import threading
from datetime import datetime, timedelta, timezone

DAILY_LIMIT = 10

usage_tracker = {}
usage_lock = threading.Lock()


def check_and_update_usage(user_id: str) -> bool:
    with usage_lock:
        today_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        user_data = usage_tracker.get(user_id)

        if not user_data or user_data.get("date") != today_str:
            usage_tracker[user_id] = {"date": today_str, "count": 1}
            print(f"Usage Tracking: New day/user '{user_id}'. Count: 1")
            return True

        if user_data["count"] < DAILY_LIMIT:
            user_data["count"] += 1
            print(f"Usage Tracking: User '{user_id}'. Count: {user_data['count']}")
            return True

        print(f"Usage Tracking: User '{user_id}' has reached the daily limit of {DAILY_LIMIT}.")
        return False
