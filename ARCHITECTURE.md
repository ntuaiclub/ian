# Architecture

## 系統架構

```
使用者 (Discord / FB / LINE)
        │
        ▼
  ┌──────────────────────────┐    ┌──────────────────────────┐
  │ Gateway 層               │    │ MCP Tool Server           │
  │ ian.gateways             │◄──►│ ian.gateways             │
  │ - discord_bot            │    │ - mcp_server             │
  │ - webhook_server         │    │ - Hybrid RAG             │
  │ - facebook_webhook       │    │                          │
  │ - line_webhook           │    │                          │
  │                          │    │ - 課程 / 通知 / 綁定工具 │
  └────────────┬─────────────┘    └──────────────────────────┘
               │                              ▲
               │                    ┌──────────────────────────┐
               │                    │ Member Store             │
               │                    │ ian.services             │
               │                    │ Google Apps Script       │
               │                    │ ⇄ Local JSON Cache       │
               │                    └──────────────────────────┘
           ▼
  ┌──────────────────────────┐
  │ Agent Runtime            │
  │ ian.services             │
  │ - agent/                 │
  │ - LangGraph ReAct        │
  │ - Gemini 3 Flash         │
  └──────────────────────────┘
```

### 各層職責

- **Gateway 層**：各平台入口。`ian.gateways.discord_bot` 處理 Discord Slash Commands；`ian.gateways.webhook_server` (Flask) 負責 Webhook route wiring，並委派給 `ian.gateways.facebook_webhook` 與 `ian.gateways.line_webhook` 處理 Facebook Messenger / LINE 平台細節。
- **Host Agent Client**：`ian.services.agent` 使用 LangGraph `create_react_agent` 搭配 Google Gemini 3 Flash，透過 MCP 協定調用工具，並管理每位使用者的獨立對話 session。
- **MCP Tool Server**：`ian.gateways.mcp_server` 以 FastMCP 框架透過 SSE 提供 RAG 搜尋、課程查詢、幹部通知、社員綁定、簽到碼產生、訂閱管理、個性備註等工具。
- **Member DB**：`ian.services.member_store` 從 Google Apps Script API 同步社員資料至本地 JSON 快取，提供平台帳號查詢、角色辨識、Email 綁定、訂閱管理與個性備註功能。

## 專案結構

```
ntuai-watson-agent/
├── src/
│   └── ian/
│       ├── config.py       # 共用環境變數、路徑與時區設定
│       ├── domain/         # 無 I/O 的純邏輯：injection、URL、member、course、reminder
│       ├── services/       # 有狀態或 I/O 的服務邊界
│       ├── gateways/       # Discord、Webhook、MCP 平台 adapter
│       └── cli.py          # Typer CLI：`ian ...`
├── tests/
│   ├── domain/             # 純邏輯 pytest 覆蓋
│   ├── services/           # service 邊界 pytest 覆蓋
│   ├── agent/              # Agent runtime placeholder（目前 intentionally skipped）
│   └── integration/        # MCP/LLM/平台整合測試 placeholder（目前 intentionally skipped）
├── start.sh                # 容器啟動腳本（依序啟動各服務）
├── Dockerfile              # NVIDIA CUDA 12.1 + Python 3.11 映像
├── docker-compose.yml      # 含 GPU 支援與 ngrok tunnel
├── Makefile                # 常用本機開發與 Docker 指令捷徑
├── .python-version         # uv 本機 Python 版本固定檔
├── .pre-commit-config.yaml # pre-commit 本機檢查設定
├── pyproject.toml          # Python 專案 metadata 與依賴群組
├── uv.lock                 # 可重現安裝的依賴 lockfile
├── .env.example            # 環境變數範本
└── data/
    ├── ntuai_zh_base.md                # Markdown 知識庫文件（RAG 資料來源）
    ├── ntuai_recompiled_index.jsonl    # QA 知識庫（JSONL 格式）
    ├── member_db.json                  # 社員資料本地快取
    └── member_mapping.csv              # FB 帳號→角色 fallback 對照表
```

## 核心元件

### Host Agent Client (`ian.services.agent`)

- 使用 **LangGraph** `create_react_agent` 搭配 **Google Gemini 3 Flash** (`gemini-3-flash-preview`) 建立 ReAct 推理迴圈。
- 每位使用者擁有獨立 session（含 `MemorySaver` 對話記憶），閒置 15 分鐘自動過期。
- 透過 **MCP streamable-http** 連接 MCP Server 取得工具。
- 內建 **每日用量限制**（每位使用者 10 次 / 日，UTC+8 午夜重置）。
- 整合 **Prompt Injection 偵測**，攔截惡意輸入。
- **URL 驗證**：從 system prompt 與工具結果中提取合法 URL，攔截 LLM 幻覺連結。
- 所有互動記錄（使用者訊息、工具呼叫、工具結果、Agent 回應、錯誤、Session 事件）即時推送至 **Discord Log Channel**。
- 支援 `[NO_RESPONSE]` 機制，Agent 可選擇不回應（搭配可選 emoji reaction）。
- 啟動時自動發送系統通知至 Discord Log Channel。

### MCP Tool Server (`ian.gateways.mcp_server`)

基於 **FastMCP** 框架，透過 streamable-http 傳輸提供以下工具：

| 工具名稱 | 功能 | 參數 |
|----------|------|------|
| `course_retreviler` | 課程 / 活動資料語意搜尋 | `platform`, `account_id`, `query`, `channel_id` |
| `qa_retreviler` | 社團 FAQ 混合搜尋 (BM25 + Semantic) | `query`, `top_k` |
| `notify_staff` | 幹部通知（透過 Discord 頻道） | `message`, `user_name`, `platform`, `context` |
| `notify_members` | 幹部發送社員通知（Discord DM） | `role`, `event_date`, `note`, `custom_message` |
| `generate_checkin_code` | 產生使用者專屬的活動簽到碼連結 | `platform`, `account_id`, `name`, `email` |
| `bind_email` | 透過 Email 綁定社員身分 | `email`, `platform`, `account_id` |
| `update_subscribe` | 更新每日課程通知訂閱設定（discord） | `platform`, `account_id`, `subscribe` |
| `update_personal_prompt` | 記錄使用者溝通風格與偏好（最多 100 字） | `platform`, `account_id`, `personal_prompt` |

**Hybrid RAG 系統**：

- 結合 **BM25** 關鍵字搜尋（jieba 中文分詞）與 **FAISS** 語意向量搜尋（`paraphrase-multilingual-MiniLM-L12-v2`），加權混合排序後回傳結果。
- 支援 FAISS 索引快取（基於來源文件 hash 自動重建）與 GPU 加速。

**課程資料**：

- 從 Google Sheets CSV 自動載入，每 30 分鐘更新一次，並快取至本地檔案。
- 支援**權限控制**：社員專屬欄位（線上連結、錄影檔案、課程照片、課程講義、備註）僅對已驗證社員或白名單頻道開放。

**社員通知（`notify_members`）**：

- 僅限幹部使用（硬邏輯檢查角色是否包含「社長」、「部長」、「部員」）。
- **活動通知模式**：選擇課程資料庫中的活動，自動帶入完整資訊（日期、時間、地點、講者、大綱等）發送給所有綁定社員。
- **自訂通知模式**：直接提供自訂訊息內容，不需選擇活動。
- 未指定活動時，自動列出即將舉辦的 3 場活動供選擇。
- 透過 Discord DM 發送。

### Daily Event Reminder (`ian.services.reminder_runner`)

- 每日 **19:00 UTC+8** 自動檢查隔天是否有活動，若有則 DM 通知所有已綁定帳號的有效社員。
- 通知內容包含完整活動資訊（課程大綱、講者、是否直播/錄影、講義連結、課程對象等），自動處理空值。
- 透過 **Discord DM** 發送。
- 支援個人化簽到連結（`QuickRecord`）。
- 支援 `--daemon` 模式（容器內常駐）、`--dry` 模擬執行、`--date` 指定日期檢查。
- 發送結果記錄至 Discord Log Channel。

### Member DB (`ian.services.member_store`)

- 從 **Google Apps Script API** 同步社員資料至本地 JSON 快取。
- 支援依平台帳號 ID（Discord / FB）查詢社員身分與角色。
- 角色分類：幹部（STAFF）、VIP 社員、一般社員、非社員（含過期判定）。
- **Email 綁定**：使用者可透過 Email 將平台帳號與社員身分關聯，綁定結果同步回 API。
- **訂閱管理**：社員可選擇在 Discord 接收每日課程通知。
- **個性備註**：記錄使用者溝通風格與偏好（最多 100 字），供 Agent 調整回應方式。
- 背景定時同步（每日 UTC+8 午夜），確保資料與 Google Sheets 一致。

### Prompt Injection 偵測 (`ian.domain.injection`)

- 獨立的 Prompt Injection / Jailbreak 偵測模組。
- **強偵測模式**：角色覆寫、指令覆蓋、結構注入等單一命中即攔截。
- **弱偵測模式**：多重弱信號（如可疑關鍵字組合）累積觸發（3 個以上）。
- **零寬字元過濾**：自動移除 U+200B、U+200C、U+200D、U+FEFF 等繞過字元。

### Discord Bot (`ian.gateways.discord_bot`)

| Slash Command | 說明 |
|---------------|------|
| `/ask <prompt>` | 向 Agent 提問 |
| `/faq` | 顯示常見問題按鈕（社課時間、社費、AI 基礎、專案組） |
| `/clear` | 清除對話記憶 |

- 自動提取 Discord 成員角色（排除 @everyone），並整合 member_db 角色資訊。
- 支援 `[NO_RESPONSE]` 靜默回應或 emoji-only 回應。

### FB / LINE Webhook (`ian.gateways.webhook_server`)

Flask Web Server，接收各平台 webhook 並在背景執行緒處理訊息。`webhook_server` 保留 Flask route 與健康檢查；Facebook Messenger 行為位於 `ian.gateways.facebook_webhook`，LINE 行為位於 `ian.gateways.line_webhook`，共用時間與聊天紀錄 helper 位於 `ian.gateways.messaging_common`。

| 平台 | 端點 | 說明 |
|------|------|------|
| Facebook | `GET /` | Webhook 驗證 |
| Facebook | `POST /` | 接收 Messenger 私訊 |
| LINE | `POST /line/callback` | 白名單群組內訊息 |
| 狀態 | `GET /status` | 服務健康檢查 |

**訊息處理特性：**

- 訊息去重快取（600 秒過期）防止重複處理。
- Facebook 支援 typing indicator 與 emoji reaction。
- LINE 支援 loading animation（20 秒延遲）、訊息分段（2000 字上限，最多 5 段）、過期 reply_token 的 push message fallback。
- 使用者角色：優先查詢 member_db，fallback 至 CSV 對照表。

## 技術棧

| 分類 | 技術 |
|------|------|
| LLM | Google Gemini 3 Flash (`gemini-3-flash-preview`) |
| Agent Framework | LangGraph + LangChain |
| Tool Protocol | Model Context Protocol (MCP) via FastMCP |
| Embedding | `paraphrase-multilingual-MiniLM-L12-v2` (HuggingFace) |
| Vector Store | FAISS (GPU / CUDA 12.1) |
| 中文分詞 | jieba |
| Web Framework | Flask (async) |
| Bot SDK | discord.py、LINE Bot SDK |
| Transport | MCP streamable-http via Starlette + Uvicorn |
| 社員資料 | Google Apps Script API + 本地 JSON 快取 |
| 課程資料 | Google Sheets CSV（自動定時更新） |
| Infrastructure | Docker (NVIDIA CUDA 12.1)、Docker Compose、ngrok |
