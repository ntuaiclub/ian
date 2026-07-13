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

from ian.utils.logging import log_event

TIMEOUT_SECONDS = 900

sessions: dict[str, dict] = {}
sessions_lock = threading.Lock()


def clear_session_if_timeout(session_id: str, current_timestamp: float):
    """若 session 已逾時則清除。需在持有 sessions_lock 時呼叫。"""
    if session_id in sessions:
        last_time = sessions[session_id].get("last_interaction_time")
        if last_time and (current_timestamp - last_time > TIMEOUT_SECONDS):
            sessions.pop(session_id)
            log_event(
                "session_expired",
                "agent_sessions",
                status="cleared",
                session_id=session_id,
            )
        elif not last_time:
            log_event(
                "session_invalid",
                "agent_sessions",
                level="warning",
                status="missing_timestamp",
                session_id=session_id,
            )


def upsert_session(
    session_id: str,
    user_name: str,
    user_role: str,
    channel_id: str,
    current_timestamp: float,
) -> tuple[dict, bool]:
    """Create or refresh a session. Caller must hold sessions_lock."""
    if session_id not in sessions:
        sessions[session_id] = {
            "agent": None,
            "memory": None,
            "user_role": user_role,
            "user_name": user_name,
            "channel_id": channel_id,
            "last_interaction_time": current_timestamp,
        }
        log_event(
            "session_created",
            "agent_sessions",
            status="success",
            session_id=session_id,
        )
        return sessions[session_id], True

    sessions[session_id]["last_interaction_time"] = current_timestamp
    sessions[session_id]["user_name"] = user_name
    sessions[session_id]["channel_id"] = channel_id
    log_event(
        "session_updated",
        "agent_sessions",
        status="success",
        session_id=session_id,
    )
    return sessions[session_id], False


def set_session_agent(session_id: str, agent, memory):
    """Set the LangGraph agent and memory. Caller must hold sessions_lock."""
    sessions[session_id]["agent"] = agent
    sessions[session_id]["memory"] = memory


def get_session_agent_and_channel(session_id: str):
    """Return the current agent and channel ID. Caller must hold sessions_lock."""
    return sessions[session_id]["agent"], sessions[session_id].get("channel_id")


def reset_session_agent(session_id: str, user_name: str):
    """Clear damaged agent state after an invocation failure. Caller must hold sessions_lock."""
    if session_id in sessions:
        sessions[session_id]["agent"] = None
        sessions[session_id]["memory"] = None
        log_event(
            "session_reset",
            "agent_sessions",
            level="warning",
            status="success",
            session_id=session_id,
            reason="invalid_chat_history",
        )


async def clear_session(session_id: str):
    """手動清除指定 session（例如使用者執行 /clear）。"""
    with sessions_lock:
        if session_id in sessions:
            sessions.pop(session_id)
            log_event(
                "session_cleared",
                "agent_sessions",
                status="success",
                session_id=session_id,
            )
        else:
            log_event(
                "session_clear_skipped",
                "agent_sessions",
                status="not_found",
                session_id=session_id,
            )
