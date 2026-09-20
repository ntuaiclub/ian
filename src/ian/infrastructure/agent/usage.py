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
from datetime import datetime, timedelta, timezone

from ian.utils.logging import log_event

DAILY_LIMIT = 10

usage_tracker = {}
usage_lock = threading.Lock()


def check_and_update_usage(user_id: str) -> bool:
    with usage_lock:
        today_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        user_data = usage_tracker.get(user_id)

        if not user_data or user_data.get("date") != today_str:
            usage_tracker[user_id] = {"date": today_str, "count": 1}
            log_event(
                "usage_updated",
                "agent_usage",
                status="allowed",
                user_id=user_id,
                usage_count=1,
                usage_limit=DAILY_LIMIT,
            )
            return True

        if user_data["count"] < DAILY_LIMIT:
            user_data["count"] += 1
            log_event(
                "usage_updated",
                "agent_usage",
                status="allowed",
                user_id=user_id,
                usage_count=user_data["count"],
                usage_limit=DAILY_LIMIT,
            )
            return True

        log_event(
            "usage_limit_reached",
            "agent_usage",
            level="warning",
            status="rate_limited",
            user_id=user_id,
            usage_count=user_data["count"],
            usage_limit=DAILY_LIMIT,
        )
        return False
