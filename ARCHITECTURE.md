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
               │                    │ Member MCP               │
               │                    │ ntuai.dev/api/mcp        │
               │                    │ Users + Memberships      │
               │                    │ Single Source of Truth   │
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

- **Domain 層**：`ian.domain` 保存 Event、Member 與純規則，不依賴環境設定或外部 SDK。
- **Application 層**：`ian.application` 保存 Event、Member、提醒與社員通知 use cases，以及 application 所擁有的 repository／notification Protocol。
- **Infrastructure 層**：`ian.infrastructure.payload_mcp` 實作 Payload MCP transport 與 Event／Member repository adapters。
- **Bootstrap**：`ian.bootstrap` 是 concrete repositories、application services 與 notification sender 的唯一組裝點；組裝本身不執行網路 I/O。
- **Gateway 層**：各平台入口。`ian.gateways.discord_bot` 處理 Discord Slash Commands；`ian.gateways.webhook_server` (Flask) 負責 Webhook route wiring，並委派給 `ian.gateways.facebook_webhook` 與 `ian.gateways.line_webhook` 處理 Facebook Messenger / LINE 平台細節。
- **Host Agent Client**：`ian.services.agent` 使用 LangGraph `create_react_agent` 搭配 Google Gemini 3 Flash，透過 MCP 協定調用工具，並管理每位使用者的獨立對話 session。
- **MCP Tool Server**：`ian.gateways.mcp_server` 以 FastMCP 框架透過 streamable HTTP 提供 RAG 搜尋、課程查詢、幹部通知、社員綁定、簽到碼產生、訂閱管理、個性備註等工具。
- **Payload MCP**：application 的 repository Protocol 由 `ian.infrastructure.payload_mcp` adapters 實作，透過 `ntuai.dev/api/mcp` 存取 Events、Users 與 Memberships；遠端網站是唯一來源。

## 專案結構

```
ntuai-watson-agent/
├── src/
│   └── ian/
│       ├── domain/         # 無 I/O 的 models 與純規則
│       ├── application/    # use cases、DTO 與 outbound Protocols
│       ├── infrastructure/ # Payload MCP concrete adapters
│       ├── gateways/       # Discord、Webhook、FastMCP inbound adapters
│       ├── services/       # 暫留 Agent、RAG、notification adapter 與 runners
│       ├── bootstrap.py    # 唯一 dependency composition root
│       ├── config.py       # 環境變數與檔案路徑設定
│       └── cli.py          # Typer CLI：`ian ...`
├── tests/
│   ├── domain/             # 純邏輯 pytest 覆蓋
│   ├── services/           # service 邊界 pytest 覆蓋
│   ├── agent/              # Agent runtime placeholder（目前 intentionally skipped）
│   └── integration/        # MCP/LLM/平台整合測試 placeholder（目前 intentionally skipped）
├── Dockerfile              # NVIDIA CUDA 12.1 + Python 3.11 映像
├── docker-compose.yml      # 含 GPU 支援與 ngrok tunnel
├── Makefile                # 常用本機開發與 Docker 指令捷徑
├── .python-version         # uv 本機 Python 版本固定檔
├── .pre-commit-config.yaml # pre-commit 本機檢查設定
├── pyproject.toml          # Python 專案 metadata 與依賴群組
├── uv.lock                 # 可重現安裝的依賴 lockfile
├── .env.example            # 環境變數範本
```text
Discord / Facebook / LINE / FastMCP / CLI
              |
              v
          ian.gateways
              |
              v
         ian.application  --->  ian.domain
              ^
              |
      ian.infrastructure.payload_mcp
              |
              v
     ntuai.dev Payload MCP (Events / Users / Memberships)

ian.bootstrap 是 application 與 infrastructure 的唯一組裝點。
Agent runtime 與 RAG 暫留 ian.services，作為後續獨立重構範圍。
```
| `notify_members` | 幹部依每位社員選定的平台發送通知 | `platform`, `account_id`, `event_id`, `note`, `custom_message` |
| `generate_checkin_code` | 產生使用者專屬的活動簽到碼連結 | `platform`, `account_id`, `name`, `email` |
| `bind_email` | 透過 Email 綁定社員身分 | `email`, `platform`, `account_id` |
| `update_subscribe` | 更新每日課程通知訂閱設定（discord、fb、line） | `platform`, `account_id`, `subscribe` |
| `update_personal_prompt` | 記錄使用者溝通風格與偏好（最多 100 字） | `platform`, `account_id`, `personal_prompt` |

**Hybrid RAG 系統**：

- 結合 **BM25** 關鍵字搜尋（jieba 中文分詞）與 **FAISS** 語意向量搜尋（`paraphrase-multilingual-MiniLM-L12-v2`），加權混合排序後回傳結果。
- 支援 FAISS 索引快取（基於來源文件 hash 自動重建）與 GPU 加速。

**活動資料**：

- Events 只透過 ntuai.dev Payload MCP 的 `findEvents` 讀取，不使用本地 CSV 或 stale cache。
- `PayloadMcpEventRepository` 固定使用公開欄位 allowlist，排除 `checkIns` 等非顯示資料。
- `EventService` 依 Event `minimumTier` 與使用者有效 Membership tier 控制查詢與通知資格。

**社員通知（`notify_members`）**：

- 僅限 ntuai.dev Users `role` 為 `admin` 或 `check-in-staff` 的已綁定使用者。
- **活動通知模式**：以 Event ID 精確選擇 published Event，依 `minimumTier` 過濾收件者後發送。
- **自訂通知模式**：直接提供自訂訊息內容，不需選擇活動。
- 未指定活動時，自動列出即將舉辦的 3 場活動供選擇。
- 依每位社員的單一 `subscribe` 平台，透過 Discord、Facebook 或 LINE 發送。

### Daily Event Reminder (`ian.services.reminder_runner`)

- 每日 **19:00 UTC+8** 透過 Event MCP 檢查隔天活動，依每位收件者 tier 過濾後發送。
- 通知內容包含完整活動資訊（課程大綱、講者、是否直播/錄影、講義連結、課程對象等），自動處理空值。
- 依每位社員的單一 `subscribe` 平台，透過 Discord、Facebook 或 LINE 發送。
- 支援個人化簽到連結（`QuickRecord`）。
- 支援 `--daemon` 模式（容器內常駐）、`--dry` 模擬執行、`--date` 指定日期檢查。
- 發送結果記錄至 Discord Log Channel。

### Member Application (`ian.application.members`)

- `ntuai.dev` 的 Users 與 Memberships 是社員資料唯一來源；不匯入、不讀取本地舊資料。
- 支援依 Discord、Facebook、LINE account ID 或已驗證 Email 查詢與綁定。
- tier 0 為非社員／過期；tier 1、2、3 分別為講座探索、動手實作、專案實作。
- `subscribe` 只能是 `discord`、`fb`、`line` 其中一個字串，`null` 代表取消訂閱。
- `personal_prompt` 是最多 100 字的使用者備註，供 Agent 注入 `User note`。
- MCP response 進入 runtime 前會經 Pydantic schema、時區與單一有效會籍檢查。

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

- 依 ntuai.dev MCP 的有效 Membership tier 判定社員角色。
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
- 使用者角色只依 ntuai.dev MCP 的有效 Membership 判定。

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
| 社員資料 | ntuai.dev MCP（Users + Memberships） |
| 活動資料 | ntuai.dev Payload MCP（Events） |
| Infrastructure | Docker (NVIDIA CUDA 12.1)、Docker Compose、ngrok |
