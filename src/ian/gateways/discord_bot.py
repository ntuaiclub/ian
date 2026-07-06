# SPDX-FileCopyrightText: 2026 NTU AI Club
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import json
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

UPLOAD_DIR = "uploads"
CHAT_HISTORY_FILE = os.path.join(UPLOAD_DIR, "chat_history.jsonl")


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
        print(f"Error saving chat history: {e}")


# FAQ 按鈕視圖
class FAQView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def ask_llm(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.defer(ephemeral=True)

        user = interaction.user

        db_role = get_member_role_from_db("Discord", str(user.id))
        roles = [db_role]

        current_time = get_current_time()

        try:
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
                print("Discord: Agent 決定不回覆此訊息")
                if agent_result.reaction_emoji:
                    await interaction.followup.send(agent_result.reaction_emoji)
                return
            await interaction.followup.send(agent_result.text)

        except Exception as e:
            await interaction.followup.send("⚠️ Error.")
            print(f"Error processing FAQ button: {e}")

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
    print("社員資料庫已初始化 (discord_chatbot)")
except Exception as e:
    print(f"社員資料庫初始化失敗: {e}")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync()
    start_log_processor()
    send_startup_notification()
    print(f"Bot 已上線：{bot.user}")

@bot.tree.command(name="ask", description="Ask Avatar.")
@app_commands.describe(prompt="歡迎詢問 NTUAI! Ask anything about NTUAI!")
async def ask(interaction: discord.Interaction, prompt: str):
    user = interaction.user

    db_role = get_member_role_from_db("Discord", str(user.id))
    roles = [db_role]

    current_time = get_current_time()
    await interaction.response.defer()

    print(
        f"\n---\n{current_time['nowdatetime']} {interaction.channel} ({interaction.channel_id})\n"
        f"{user.display_name} ({user.global_name}, {user.name}, {roles})\n詢問：{prompt}\n"
    )

    try:
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
            print("Discord: Agent 決定不回覆此訊息")
            if agent_result.reaction_emoji:
                await interaction.followup.send(agent_result.reaction_emoji)
            return
        await interaction.followup.send(agent_result.text)
        save_chat_history(user.name, user.display_name, prompt, agent_result.text)
        print("Message processed successfully")

    except Exception as e:
        await interaction.followup.send("⚠️ Error.")
        print(f"Error processing message: {e}")

@bot.tree.command(name="faq", description="常見問題")
async def faq(interaction: discord.Interaction):
    await interaction.response.send_message(
        "點選下方按鈕查看常見問題：", view=FAQView()
    )

@bot.tree.command(name="clear", description="清除記憶")
async def clear(interaction: discord.Interaction):
    try:
        await clear_session(interaction.user.name)
        await interaction.response.send_message("🫥 已清除記憶，請開始新的對話。\nCleared. Please start a new conversation.")
    except Exception as e:
        await interaction.response.send_message("⚠️ Error.")
        print(f"Error clearing session: {e}")

def entrypoint():
    if not DISCORD_BOT_TOKEN:
        print("Error: DISCORD_BOT_TOKEN not found in environment variables.")
        raise SystemExit(1)
    bot.run(DISCORD_BOT_TOKEN)
