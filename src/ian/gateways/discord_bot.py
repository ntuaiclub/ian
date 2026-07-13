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

import os
import json
import time
import discord
from discord.ext import commands
from discord import app_commands

from ian.config import DISCORD_BOT_TOKEN
from ian.gateways.agent_bridge import run_agent_message_flow
from ian.gateways.messaging_common import get_current_time
from ian.services.agent import (
    start_log_processor,
    send_startup_notification,
    clear_session,
)
from ian.services.member_store import get_member_role as get_member_role_from_db, init as init_member_db
from ian.utils.logging import elapsed_ms, hash_identifier, log_event

UPLOAD_DIR = "uploads"
CHAT_HISTORY_FILE = os.path.join(UPLOAD_DIR, "chat_history.jsonl")


def _interaction_correlation_id(interaction: discord.Interaction) -> str:
    return hash_identifier(getattr(interaction, "id", None) or interaction.user.id)


def save_chat_history(sender_id, user_name, user_message, bot_response):
    """將對話記錄以 JSONL 格式追加寫入檔案。"""
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    current_time_data = get_current_time()
    new_entry = {
        "timestamp": current_time_data["nowdatetime"],
        "platform": "Discord",
        "sender_id": sender_id,
        "user_name": user_name,
        "user_message": user_message,
        "bot_response": bot_response,
    }
    try:
        with open(CHAT_HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(new_entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log_event(
            "job_failed",
            "discord_bot",
            level="error",
            platform="Discord",
            status="error",
            job="save_chat_history",
            sender_id=sender_id,
            error=e,
        )


# FAQ 按鈕視圖
class FAQView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def ask_llm(self, interaction: discord.Interaction, prompt: str):
        started_at = time.monotonic()
        correlation_id = _interaction_correlation_id(interaction)
        await interaction.response.defer(ephemeral=True)

        user = interaction.user

        db_role = get_member_role_from_db("Discord", str(user.id))
        roles = [db_role]

        current_time = get_current_time()

        log_event(
            "request_received",
            "discord_bot",
            platform="Discord",
            status="accepted",
            correlation_id=correlation_id,
            interaction_id=getattr(interaction, "id", None),
            user_id=str(user.id),
            channel_id=str(interaction.channel_id),
            source="faq",
            message_length=len(prompt),
        )
        try:
            log_event(
                "agent_invoked",
                "discord_bot",
                platform="Discord",
                status="started",
                correlation_id=correlation_id,
                user_id=str(user.id),
            )
            agent_result = await run_agent_message_flow(
                session_id=user.name,
                user_name=user.display_name,
                user_message=prompt,
                roles=roles,
                current_time=current_time,
                channel_id=str(interaction.channel_id),
                platform="Discord",
                account_id=str(user.id),
            )
            if not agent_result.should_reply:
                log_event(
                    "no_response",
                    "discord_bot",
                    platform="Discord",
                    status="success",
                    duration_ms=elapsed_ms(started_at),
                    correlation_id=correlation_id,
                    user_id=str(user.id),
                    reason="agent_decision",
                )
                if agent_result.reaction_emoji:
                    await interaction.followup.send(agent_result.reaction_emoji)
                return
            await interaction.followup.send(agent_result.text)
            log_event(
                "reply_sent",
                "discord_bot",
                platform="Discord",
                status="success",
                duration_ms=elapsed_ms(started_at),
                correlation_id=correlation_id,
                user_id=str(user.id),
            )

        except Exception as e:
            await interaction.followup.send("⚠️ Error.")
            log_event(
                "request_failed",
                "discord_bot",
                level="error",
                platform="Discord",
                status="error",
                duration_ms=elapsed_ms(started_at),
                correlation_id=correlation_id,
                user_id=str(user.id),
                error=e,
            )

    @discord.ui.button(
        label="社課時間？", style=discord.ButtonStyle.secondary, custom_id="faq_time"
    )
    async def time_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.ask_llm(interaction, "請問 NTUAI 的社課時間是什麼時候？")

    @discord.ui.button(
        label="社費多少？", style=discord.ButtonStyle.secondary, custom_id="faq_fee"
    )
    async def fee_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.ask_llm(interaction, "加入 NTUAI 社團需要多少社費？")

    @discord.ui.button(
        label="需要 AI 基礎嗎？",
        style=discord.ButtonStyle.secondary,
        custom_id="faq_ai",
    )
    async def ai_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.ask_llm(interaction, "參加 NTUAI 的課程需要有 AI 基礎嗎？")

    @discord.ui.button(
        label="怎麼加入專案組？",
        style=discord.ButtonStyle.secondary,
        custom_id="faq_project",
    )
    async def project_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.ask_llm(interaction, "想加入 NTUAI 的專案組需要什麼條件？")

# Initialize member database
try:
    init_member_db()
    log_event(
        "job_completed",
        "discord_bot",
        platform="Discord",
        status="success",
        job="member_store_initialization",
    )
except Exception as e:
    log_event(
        "job_failed",
        "discord_bot",
        level="error",
        platform="Discord",
        status="error",
        job="member_store_initialization",
        error=e,
    )

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync()
    start_log_processor()
    send_startup_notification()
    log_event(
        "service_ready",
        "discord_bot",
        platform="Discord",
        status="ready",
        service="discord_bot",
    )

@bot.tree.command(name="ask", description="Ask Avatar.")
@app_commands.describe(prompt="歡迎詢問 NTUAI! Ask anything about NTUAI!")
async def ask(interaction: discord.Interaction, prompt: str):
    started_at = time.monotonic()
    correlation_id = _interaction_correlation_id(interaction)
    user = interaction.user

    db_role = get_member_role_from_db("Discord", str(user.id))
    roles = [db_role]

    current_time = get_current_time()
    await interaction.response.defer()

    log_event(
        "request_received",
        "discord_bot",
        platform="Discord",
        status="accepted",
        correlation_id=correlation_id,
        interaction_id=getattr(interaction, "id", None),
        user_id=str(user.id),
        channel_id=str(interaction.channel_id),
        source="slash_command",
        message_length=len(prompt),
    )

    try:
        log_event(
            "agent_invoked",
            "discord_bot",
            platform="Discord",
            status="started",
            correlation_id=correlation_id,
            user_id=str(user.id),
        )
        agent_result = await run_agent_message_flow(
            session_id=user.name,
            user_name=user.display_name,
            user_message=prompt,
            roles=roles,
            current_time=current_time,
            channel_id=str(interaction.channel_id),
            platform="Discord",
            account_id=str(user.id),
        )
        if not agent_result.should_reply:
            log_event(
                "no_response",
                "discord_bot",
                platform="Discord",
                status="success",
                duration_ms=elapsed_ms(started_at),
                correlation_id=correlation_id,
                user_id=str(user.id),
                reason="agent_decision",
            )
            if agent_result.reaction_emoji:
                await interaction.followup.send(agent_result.reaction_emoji)
            return
        await interaction.followup.send(agent_result.text)
        save_chat_history(user.name, user.display_name, prompt, agent_result.text)
        log_event(
            "reply_sent",
            "discord_bot",
            platform="Discord",
            status="success",
            duration_ms=elapsed_ms(started_at),
            correlation_id=correlation_id,
            user_id=str(user.id),
        )

    except Exception as e:
        await interaction.followup.send("⚠️ Error.")
        log_event(
            "request_failed",
            "discord_bot",
            level="error",
            platform="Discord",
            status="error",
            duration_ms=elapsed_ms(started_at),
            correlation_id=correlation_id,
            user_id=str(user.id),
            error=e,
        )

@bot.tree.command(name="faq", description="常見問題")
async def faq(interaction: discord.Interaction):
    await interaction.response.send_message(
        "點選下方按鈕查看常見問題：", view=FAQView()
    )

@bot.tree.command(name="clear", description="清除記憶")
async def clear(interaction: discord.Interaction):
    correlation_id = _interaction_correlation_id(interaction)
    try:
        await clear_session(interaction.user.name)
        await interaction.response.send_message("🫥 已清除記憶，請開始新的對話。\nCleared. Please start a new conversation.")
    except Exception as e:
        await interaction.response.send_message("⚠️ Error.")
        log_event(
            "request_failed",
            "discord_bot",
            level="error",
            platform="Discord",
            status="error",
            correlation_id=correlation_id,
            user_id=str(interaction.user.id),
            operation="clear_session",
            error=e,
        )

def entrypoint():
    if not DISCORD_BOT_TOKEN:
        log_event(
            "job_failed",
            "discord_bot",
            level="critical",
            platform="Discord",
            status="error",
            job="bot_startup",
            reason="missing_bot_token",
        )
        raise SystemExit(1)
    bot.run(DISCORD_BOT_TOKEN)
