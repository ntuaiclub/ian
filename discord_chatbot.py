import os
import json
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta, timezone
import asyncio
from host_agent_client import (
    start_dispatcher,
    start_log_processor,
    send_startup_notification,
    chat_with_agent,
    clear_session,
    parse_no_response,
)
from member_db import get_member_role as get_member_role_from_db, init as init_member_db

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

def get_current_time():
    """回傳台灣時區 (UTC+8) 的時間資訊 dict。"""
    now = datetime.now(timezone(timedelta(hours=8)))
    return {
        "nowdatetime": now.strftime("%Y/%m/%d %H:%M:%S"),
        "nowday": now.strftime("%A"),
        "timestamp": now.timestamp()
    }

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
            start_dispatcher(user.display_name, current_time)

            response = await chat_with_agent(
                user.name,
                user.display_name,
                prompt,
                roles,
                current_time["timestamp"],
                str(interaction.channel_id),
                platform="Discord",
                account_id=str(user.id),
            )
            is_no_response, reaction_emoji = parse_no_response(response)
            if is_no_response:
                print(f"Discord: Agent 決定不回覆此訊息")
                if reaction_emoji:
                    await interaction.followup.send(reaction_emoji)
                return
            await interaction.followup.send(response)
            
        except Exception as e:
            await interaction.followup.send(f"⚠️ Error.")
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
        start_dispatcher(user.display_name, current_time)

        bot_response = await chat_with_agent(
            user.name,
            user.display_name,
            prompt,
            roles,
            current_time["timestamp"],
            str(interaction.channel_id),
            platform="Discord",
            account_id=str(user.id),
        )
        is_no_response, reaction_emoji = parse_no_response(bot_response)
        if is_no_response:
            print(f"Discord: Agent 決定不回覆此訊息")
            if reaction_emoji:
                await interaction.followup.send(reaction_emoji)
            return
        await interaction.followup.send(bot_response)
        save_chat_history(user.name, user.display_name, prompt, bot_response)
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
        await interaction.response.send_message(f"⚠️ Error.")
        print(f"Error clearing session: {e}")

if __name__ == "__main__":
    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not bot_token:
        print("Error: DISCORD_BOT_TOKEN not found in environment variables.")
        exit(1)
    bot.run(bot_token)