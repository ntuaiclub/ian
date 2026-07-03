# CONTRIBUTION.md

這份文件給本專案的貢獻者參考。開始修改前，請先讀相關檔案，而不是只依賴這份摘要。

## 先讀這些

- [`README.md`](README.md)：系統架構與核心元件說明。
- [`Makefile`](Makefile)：常用開發、測試、pre-commit、Docker 指令。
- [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/)：bug / feature issue 格式。
- [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)：PR 必填內容與影響檢查。
- 相關程式碼與測試：改哪個模組，就先讀該模組與對應 tests。

## 專案分層

- `src/ian/domain/`：無 I/O 的純邏輯，例如 prompt injection、URL、課程與社員判斷。
- `src/ian/services/`：有狀態或外部 I/O 的服務，例如 RAG、member store、agent runtime、通知。
- `src/ian/gateways/`：平台 adapter，例如 Discord、FB/LINE webhook、MCP server。
- `tests/`：pytest 測試，依 domain、services、agent 分類。

修改時請維持既有分層：純邏輯放在 `domain`，外部服務或狀態邊界放在 `services`，平台入口放在 `gateways`。

## 初始化環境

本專案使用 Python 3.11 與 `uv` 管理依賴。首次設定：

```bash
make setup
```

常用指令請看 `make help`。

## 環境變數

需要本機服務或串接平台時，先建立 `.env`：

```bash
cp .env.example .env
```

再依需求填入實際值。主要變數包含：

| 變數 | 說明 |
|------|------|
| `DISCORD_BOT_TOKEN` | Discord Bot Token |
| `DISCORD_LOG_CHANNEL_ID` | Discord 日誌頻道 ID |
| `STAFF_NOTIFICATION_CHANNEL_ID` | 幹部通知頻道 ID |
| `GOOGLE_API_KEY` | Google Gemini API Key |
| `PAGE_ACCESS_TOKEN` | Facebook Page Access Token |
| `FB_VERIFY_TOKEN` | Facebook Webhook 驗證 Token |
| `MEMBER_API_URL` | Member API URL |
| `MEMBER_API_KEY` | Member API Key |
| `COURSE_DATA_URL` | 課程資料來源 URL |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Channel Access Token |
| `LINE_CHANNEL_SECRET` | LINE Channel Secret |
| `LINE_ALLOWED_GROUPS` | LINE 白名單群組 ID（逗號分隔） |
| `NGROK_AUTHTOKEN` | ngrok Auth Token |

不要提交 `.env`、API key、token、private key、個資或真實使用者資料。

## 本地開發

查看現有 CLI 指令：

```bash
uv run ian --help
```

常見服務可分別啟動：

```bash
uv run ian mcp --http --port 5191
uv run ian webhook
uv run ian reminder --daemon
uv run ian discord
```

本專案使用 pre-commit 執行輕量的格式、lint 與 repository hygiene 檢查。首次環境設定已包含 hook 安裝；若需要手動執行所有檔案檢查：

```bash
make precommit
```

FAISS 依賴在 `pyproject.toml` 以平台 marker 明確指定：macOS 安裝 `faiss-cpu`，Linux x86_64 / CUDA 容器安裝 `faiss-gpu-cu12`。

## Docker Compose

Docker Compose 啟動需要 NVIDIA GPU 及 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)。

```bash
make docker-build
make docker-up
make docker-logs
make docker-down
```

容器啟動流程（`start.sh`）：

1. 啟動 MCP Server（port 5191），等待 health check 通過（模型載入約需 60-90 秒）。
2. 啟動 Flask Webhook Server（port 5190）。
3. 啟動 Daily Event Reminder Daemon（每日 19:00 UTC+8 自動通知）。
4. 啟動 Discord Bot。

## 貢獻流程

開始貢獻前，請先從最新主分支建立新 branch：

```bash
git switch main
git pull
git switch -c <type>/<short-description>
```

Branch 建議使用 `fix/`、`feat/`、`docs/`、`refactor/`、`test/` 或 `chore/` 前綴。

若是 bug 或功能需求，請先開 issue，並使用 [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/) 內的 template。送出 PR 時，請使用 [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)，連結相關 issue，並清楚寫出測試方式與影響範圍。

PR title 請比照 issue title 前綴，例如：

- `[Bug]: fix Discord webhook retry handling`
- `[Feature]: add member subscription settings`
- `[Docs]: update local development guide`
- `[Refactor]: simplify reminder scheduling`
- `[Test]: cover URL validation edge cases`
- `[Chore]: update dependency lockfile`

## 開發注意事項

- 優先新增或更新測試，特別是 `domain` 純邏輯、權限判斷、URL 驗證、prompt injection、member role 與 notification 行為。
- 修改 Discord、Webhook、MCP、Reminder 或 Docker 行為時，請在 PR 的 Impact Checklist 寫明驗證方式。
- 新增或變更環境變數時，必須同步更新 `.env.example` 與本文件。
- 不要在 logs、測試 fixture、文件或 PR 中暴露 token、API key、private key、個資、社員資料或平台帳號 ID。
- 對外部 API、Google Sheets、Discord、LINE、Facebook 的測試應避免依賴真實服務；能 mock 就 mock。
- RAG、FAISS、模型載入與平台 webhook 相關改動可能受環境影響，請補上可重現的本地或 Docker 驗證步驟。
- 保持 commit 與 PR 範圍聚焦，避免混入不相關格式化或重構。
- 如果遇到既有未提交變更，先確認來源；不要覆蓋或 revert 別人的修改。

## 驗證

提交 PR 前至少確認測試與 pre-commit：

```bash
make test
make precommit
```

若改到 Docker、啟動流程或平台整合，請依 `Makefile` 與本文件額外驗證對應服務。若未能執行某些檢查，請在 PR 的 Testing 區塊說明原因與風險。

## CI

GitHub Actions 會在 pull request 與 `main` branch push 時執行：

- `uv run pre-commit run --all-files`
- `uv run pytest`

CI 不依賴 production secrets、GPU、Discord/LINE/Facebook credentials、Google APIs 或 live LLM calls。需要外部服務的測試應以 mock、fixture 或 skipped integration placeholder 處理。

## 協作準則

- 先讀相關檔案與測試，再修改。
- 優先沿用既有架構、命名、測試風格。
- 只改與任務相關的檔案。
- 完成後回報實際變更與執行過的驗證指令。
