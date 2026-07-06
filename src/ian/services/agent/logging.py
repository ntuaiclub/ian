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
import time
from datetime import datetime, timedelta, timezone
from queue import Queue

from ian.config import DISCORD_LOG_CHANNEL_ID_INT
from ian.services import discord_api
from ian.utils.console import eprint

LOG_CHANNEL_ID = DISCORD_LOG_CHANNEL_ID_INT
log_queue: Queue = Queue()
log_processor_started = False


def start_log_processor():
    """啟動 log 處理器背景線程（只需呼叫一次）"""
    global log_processor_started
    if log_processor_started:
        return
    log_processor_started = True
    thread = threading.Thread(target=_process_log_queue_sync, daemon=True)
    thread.start()
    eprint(f"Discord log processor started, logging to channel {LOG_CHANNEL_ID}")


def send_startup_notification():
    """發送系統啟動通知到 Discord log channel"""
    try:
        tz_taipei = timezone(timedelta(hours=8))
        timestamp = datetime.now(tz_taipei).strftime("%Y-%m-%d %H:%M:%S")

        message = (
            "```\n"
            "===================================================\n"
            f"  SYSTEM STARTUP  |  {timestamp}\n"
            "===================================================\n"
            "  Status: ONLINE\n"
            "  Service: NTUAI Chatbot Agent\n"
            "  Platforms: Discord / Facebook / LINE\n"
            "===================================================\n"
            "```"
        )

        response = discord_api.send_channel_message(LOG_CHANNEL_ID, message)
        if response.status_code != 200:
            eprint(
                "Failed to send startup notification: "
                f"{response.status_code} - {response.text}"
            )
        else:
            eprint("Startup notification sent to Discord log channel")
    except Exception as e:
        eprint(f"Failed to send startup notification: {e}")


def _process_log_queue_sync():
    """同步背景處理 log 佇列"""
    while True:
        try:
            if not log_queue.empty():
                log_entry = log_queue.get_nowait()
                _send_log_to_discord_sync(log_entry)
            time.sleep(0.5)
        except Exception as e:
            eprint(f"Error processing log queue: {e}")


def _send_log_to_discord_sync(log_entry: dict):
    """透過 HTTP API 發送 log 到 Discord channel"""
    try:
        message = format_log_message(log_entry)
        if len(message) > 1900:
            message = message[:1900] + "...(truncated)"

        response = discord_api.send_channel_message(LOG_CHANNEL_ID, message)
        if response.status_code != 200:
            eprint(f"Failed to send log to Discord: {response.status_code} - {response.text}")
    except Exception as e:
        eprint(f"Failed to send log to Discord: {e}")


def format_log_message(log_entry: dict) -> str:
    """格式化 log 訊息為 terminal 風格"""
    log_type = log_entry.get("type", "INFO")
    timestamp = log_entry.get("timestamp", "")

    if log_type == "USER_MESSAGE":
        user = log_entry.get("user_name", "Unknown")
        role = log_entry.get("user_role", "")
        msg = log_entry.get("message", "")
        platform = log_entry.get("platform", "Unknown")
        session_id = log_entry.get("session_id", "")[:8] if log_entry.get("session_id") else ""
        return (
            f"```\n"
            f"[{timestamp}] USER_MESSAGE\n"
            f"├─ Platform : {platform}\n"
            f"├─ User     : {user}\n"
            f"├─ Role     : {role}\n"
            f"├─ Session  : {session_id}...\n"
            f"└─ Message  : {msg}\n"
            f"```"
        )

    if log_type == "TOOL_CALL":
        tool = log_entry.get("tool_name", "Unknown")
        args = log_entry.get("args", {})
        args_str = str(args)[:600] if args else "None"
        return (
            f"```\n"
            f"[{timestamp}] TOOL_CALL\n"
            f"├─ Tool : {tool}\n"
            f"└─ Args : {args_str}\n"
            f"```"
        )

    if log_type == "TOOL_RESULT":
        tool = log_entry.get("tool_name", "Unknown")
        result = str(log_entry.get("result", ""))[:600]
        return (
            f"```\n"
            f"[{timestamp}] TOOL_RESULT\n"
            f"├─ Tool   : {tool}\n"
            f"└─ Result : {result}\n"
            f"```"
        )

    if log_type == "AGENT_RESPONSE":
        user = log_entry.get("user_name", "Unknown")
        response = log_entry.get("response", "")[:800]
        response_len = len(log_entry.get("response", ""))
        return (
            f"```\n"
            f"[{timestamp}] AGENT_RESPONSE\n"
            f"├─ To     : {user}\n"
            f"├─ Length : {response_len} chars\n"
            f"└─ Response:\n{response}\n"
            f"```"
        )

    if log_type == "ERROR":
        error = log_entry.get("error", "Unknown error")
        context = log_entry.get("context", "")
        return (
            f"```\n"
            f"[{timestamp}] ERROR\n"
            f"├─ Context : {context}\n"
            f"└─ Error   : {error}\n"
            f"```"
        )

    if log_type == "SESSION":
        action = log_entry.get("action", "")
        user = log_entry.get("user_name", "Unknown")
        session = log_entry.get("session_id", "")[:12] if log_entry.get("session_id") else ""
        return (
            f"```\n"
            f"[{timestamp}] SESSION_{action.upper()}\n"
            f"├─ User    : {user}\n"
            f"└─ Session : {session}...\n"
            f"```"
        )

    msg = log_entry.get("message", str(log_entry))
    return (
        f"```\n"
        f"[{timestamp}] INFO\n"
        f"└─ {msg}\n"
        f"```"
    )


def add_log(log_type: str, **kwargs):
    """新增 log 到佇列"""
    tz_taipei = timezone(timedelta(hours=8))
    timestamp = datetime.now(tz_taipei).strftime("%H:%M:%S")
    log_entry = {"type": log_type, "timestamp": timestamp, **kwargs}
    log_queue.put(log_entry)
