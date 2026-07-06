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
import os
from datetime import datetime, timedelta, timezone

UPLOAD_DIR = "uploads"
CHAT_HISTORY_FILE = os.path.join(UPLOAD_DIR, "chat_history.json")


def get_current_time():
    """回傳台灣時區 (UTC+8) 的時間資訊 dict。"""
    now = datetime.now(timezone(timedelta(hours=8)))
    return {
        "nowdatetime": now.strftime("%Y/%m/%d %H:%M:%S"),
        "nowday": now.strftime("%A"),
        "timestamp": now.timestamp(),
    }


def save_chat_history(sender_id, user_name, user_message, bot_response, platform="FB"):
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    history = []
    if os.path.exists(CHAT_HISTORY_FILE):
        with open(CHAT_HISTORY_FILE, "r", encoding="utf-8") as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []

    time_data = get_current_time()
    history.append(
        {
            "timestamp": time_data["nowdatetime"],
            "platform": platform,
            "sender_id": sender_id,
            "user_name": user_name,
            "user_message": user_message,
            "bot_response": bot_response,
        }
    )

    with open(CHAT_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
