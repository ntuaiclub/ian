# Event MCP 技術實作文件

## 1. 文件資訊

- 狀態：Approved for implementation
- 基準日：2026-07-20
- 目標：將 Ian 的課程／活動資料唯一來源改為 `https://ntuai.dev/api/mcp` 的 Events collection
- 遷移方式：開發階段直接切換，不保留 CSV 相容層
- 影響範圍：ntuai.dev Event schema、Ian Event domain、課程搜尋、每日提醒、社員通知

## 2. 已確認決策

1. ntuai.dev Events 是活動資料唯一 source of truth。
2. 現有 Google Sheets CSV 資料已過時，不用於欄位設計、資料比對、匯入或驗收。
3. Ian 使用 ntuai.dev 的 attribute names，不建立中文 CSV 欄位 alias。
4. ntuai.dev 必須補齊講者、類別、直播／錄影、課程對象、非社員費用、線上連結、照片與備註等 Event 欄位。
5. `minimumTier` 同時控制活動查詢可見性與活動通知資格。
6. `notify_members` 使用 `event_id` 選擇活動；日期只用於查詢候選活動。
7. 專案尚未上線，不做 dual read、feature flag、資料 backfill 或 runtime CSV fallback。
8. 遷移完成後移除 `COURSE_DATA_URL`、pandas 課程模型及本地課程快取。

## 3. 非目標

- 不將舊 CSV 資料寫入 ntuai.dev。
- 不修改 Ian 以外的舊資料來源。
- 不由 Ian 建立、更新或刪除 Event；Ian 對 Events 只有 read 權限。
- 不保留 `course_data` DataFrame、中文欄位 mapping 或舊函式 alias。
- 不處理 Event 簽到名單；`checkIns` 不得被 Ian 讀取。
- 不改變自訂社員通知模式；只有活動通知模式改用 Event MCP。

## 4. 現況與問題

目前有三個獨立 Event consumer：

1. `course_retreviler` 透過 `course_catalog.py` 下載 CSV、建立 pandas DataFrame 並搜尋。
2. `reminder_runner.py` 每次執行時另外下載一次 CSV，尋找隔日活動。
3. `notify_members` 直接讀取全域 DataFrame，以日期取得第一場活動。

現況有以下問題：

- 同一份資料有兩套下載與錯誤處理邏輯。
- 本地 30 分鐘 cache 與 stale fallback 可能提供過期資料。
- pandas row 與中文欄位名稱滲透到 domain、service、gateway 和 tests。
- `notify_members` 以日期選第一筆，同日多場活動時會選錯。
- 既有權限是欄位級隱藏，無法表達不同 Event 的最低 tier。
- CSV 缺少穩定主鍵，無法安全引用特定活動。

## 5. ntuai.dev 現況基線

2026-07-20 使用 Ian 的 MCP API key 對 `findEvents` 執行 read-only audit：

- published Events：29 筆
- published 且缺少 `title`：3 筆
- 缺少 `startDate`：0 筆
- 缺少 `endDate`：0 筆
- 缺少 `location`：3 筆
- 缺少 `content`：3 筆
- `materials` 有值：1 筆
- `videoURL` 有值：0 筆
- `minimumTier` 分布：`null=16`、`0=2`、`1=2`、`2=8`、`3=1`

目前 `findEvents` 支援 `id`、`where`、`select`、`sort`、`limit`、`page`、`depth`、`draft` 與 locale 參數；單頁上限為 100 筆。現有 response 還包含 `checkIns`、`relatedCourseLessons` 等 Ian 不需要的資料，因此實作必須固定使用 `select` allowlist。

## 6. 目標架構

```text
                         ntuai.dev Payload MCP
                           Events collection
                                  |
                                  v
                       PayloadMcpToolCaller
                    transport / timeout / parsing
                                  |
                                  v
                       EventMcpRepository
               published filter / pagination / schema
                                  |
                                  v
                          EventService
                access / search / date / formatting
                   +--------------+--------------+
                   |              |              |
                   v              v              v
             event_retriever  reminder_runner  notify_members
                                                event_id
```

Gateway 不得直接呼叫 `findEvents`，也不得處理 Payload document。所有 Event 資料必須經過 `EventMcpRepository` 與 `EventService`。

## 7. ntuai.dev Event 資料契約

### 7.1 欄位

下表是 Ian 依賴的完整 Event contract。標示「新增／調整」的欄位必須先在 ntuai.dev 完成。

| 欄位 | Payload 型別 | 必填規則 | Ian 用途 |
| --- | --- | --- | --- |
| `id` | number | 系統必填 | 活動唯一識別 |
| `title` | text | published 必填且不可空白 | 搜尋、顯示、通知 |
| `startDate` | date | published 必填 | 開始時間 |
| `endDate` | date | published 必填，且不得早於 `startDate` | 結束時間 |
| `location` | text | 選填 | 實體場地或地點說明 |
| `content` | richText / Lexical JSON | 選填 | 課程大綱與活動介紹 |
| `minimumTier` | number / select | 選填，僅接受 0–3 | 查詢與通知權限 |
| `speaker` | text | 新增／選填 | 講者，可用純文字描述多人 |
| `category` | text | 新增／選填 | 活動／課程類別 |
| `audience` | textarea | 新增／選填 | 課程對象的文字說明 |
| `enableLivestream` | checkbox | 新增，預設 `false` | 是否提供直播 |
| `enableRecording` | checkbox | 新增，預設 `false` | 是否預計錄影 |
| `nonMemberFee` | number | 新增／選填，整數且不得小於 0 | 非社員報名費；0 表示免費，`null` 表示不適用或未定 |
| `onlineURL` | text | 新增／選填，僅允許 `http`/`https` | 線上活動或直播連結 |
| `materials` | array | 選填 | 講義與相關檔案；item 為 `id`、`label`、`url` |
| `videoURL` | text | 選填，僅允許 `http`/`https` | 活動錄影連結 |
| `eventMedia` | upload，`hasMany` | 調整／選填 | 活動照片；Ian 只讀公開 URL 與替代文字 |
| `notes` | textarea | 新增／選填 | 活動備註 |
| `slug` | text | published 必填且唯一 | ntuai.dev 活動頁識別 |
| `_status` | drafts status | 系統必填 | Ian 只接受 `published` |

`week`、`weekday`、顯示日期和顯示時間不儲存在 Ian，也不要求網站建立重複欄位；全部從 `startDate`、`endDate` 以 `Asia/Taipei` 推導。

### 7.2 發布驗證

ntuai.dev 在 Event 發布前必須驗證：

- `title`、`startDate`、`endDate`、`slug` 存在且有效。
- `endDate >= startDate`。
- `minimumTier` 為 `null` 或 0–3 的整數。
- URL 欄位只接受 `http` 或 `https`。
- `materials` 每筆均有非空 `label` 與合法 `url`。
- `nonMemberFee` 為非負整數。
- `_status=published` 的文件不可只有空白標題。

`location` 與 `content` 可以為空，因為線上活動或簡短公告不一定需要兩者；但資料就緒檢查必須列出缺值供內容管理者確認。

### 7.3 Tier 規則

| `minimumTier` | 活動可見與通知資格 |
| ---: | --- |
| `null` 或 `0` | 公開；tier 0–3 都可查詢 |
| `1` | 講座探索以上 |
| `2` | 動手實作以上 |
| `3` | 專案實作 |

統一判斷式：

```python
required_tier = event.minimumTier or 0
allowed = viewer_tier >= required_tier
```

`viewer_tier` 必須來自 `MemberService` 的有效 Membership；找不到使用者、會籍過期或 Member MCP 發生錯誤時一律為 tier 0。Discord／LINE 白名單頻道不得繞過 `minimumTier`。

## 8. Ian Domain Model

新增 `src/ian/domain/events.py`，取代 `domain/courses.py` 與 DataFrame-based reminder helpers。

```python
class EventMaterial(BaseModel):
    id: str
    label: str
    url: HttpUrl


class EventMedia(BaseModel):
    id: int
    url: HttpUrl
    alt: str | None = None


class Event(BaseModel):
    id: int
    title: str
    startDate: datetime
    endDate: datetime
    location: str | None = None
    content: dict | None = None
    minimumTier: int | None = Field(default=None, ge=0, le=3)
    speaker: str | None = None
    category: str | None = None
    audience: str | None = None
    enableLivestream: bool = False
    enableRecording: bool = False
    nonMemberFee: int | None = Field(default=None, ge=0)
    onlineURL: HttpUrl | None = None
    materials: list[EventMaterial] = Field(default_factory=list)
    videoURL: HttpUrl | None = None
    eventMedia: list[EventMedia] = Field(default_factory=list)
    notes: str | None = None
    slug: str
    status: Literal["published"] = Field(alias="_status")
```

Model 規則：

- `extra="ignore"`，搭配 repository `select` 防止 Payload 管理欄位滲入 domain。
- 所有 datetime 必須帶 timezone；解析後可保留 UTC，顯示時才轉 `TZ_TPE`。
- `title`、`speaker`、`category`、`audience`、`location`、`notes` trim；空字串正規化為 `None`，`title` 除外，空白 title 直接拒絕。
- `endDate < startDate` 時拋出 `EventSchemaError`。
- Event model 不保存 `weekday`、`time` 或中文顯示欄位。
- `minimumTier` 透過 `required_tier` property 將 `null` 正規化為 0，但不改寫遠端值。

### 8.1 Lexical 轉換

`content` 是 Payload Lexical JSON。Ian 新增純函式 `lexical_to_text(content)`：

- 遞迴走訪 `root.children`。
- 只讀 `text` 與子節點，不執行 HTML 或 script。
- paragraph、heading、list item 之間保留換行。
- 空 Lexical document 回傳空字串。
- 未知 node type 忽略格式但繼續走訪 children。
- 連結 URL 不從 rich text 自動信任；活動主連結使用結構化 `onlineURL`、`materials` 或 `videoURL`。

Python runtime 不引入 JavaScript converter；Payload 官方 converters 仍可供 ntuai.dev 網站端渲染使用。

## 9. 共用 MCP Transport

Member 與 Event 使用同一個 ntuai.dev endpoint。共用 transport 位於 `src/ian/infrastructure/payload_mcp/client.py`：

- `McpToolCaller` protocol
- `StreamableHttpMcpToolCaller`
- fenced JSON Payload response parser
- transport、tool 與 response parsing 的共用例外

Member repository 保留自己的 `Member*Error` 對外介面；Event repository 使用 `Event*Error`。兩者在 repository boundary 將共用 transport error 映射成 domain-specific error，gateway 不直接依賴共用 transport 例外。

環境變數統一為：

| 變數 | 預設／用途 |
| --- | --- |
| `NTUAI_MCP_URL` | 預設 `https://ntuai.dev/api/mcp` |
| `NTUAI_MCP_API_KEY` | Ian server-side MCP key |
| `NTUAI_MCP_TIMEOUT_SECONDS` | 預設 20 秒 |

專案尚未上線，因此直接將現有 `MEMBER_MCP_*` 改名，不保留環境變數 alias。開發者須同步更新本地 `.env`；secret 不可進入 Git、log 或 exception message。

Ian API key 最小權限：

- Events：find only
- Users：find、update 既有允許欄位
- Memberships：find only
- Events 的 create、update、delete 一律禁止

## 10. EventMcpRepository

Event adapter 位於 `src/ian/infrastructure/payload_mcp/event_repository.py`。

### 10.1 Select allowlist

每次 `findEvents` 固定使用 `depth=0` 與下列 `select`：

```python
EVENT_SELECT = {
    "id": True,
    "title": True,
    "startDate": True,
    "endDate": True,
    "location": True,
    "content": True,
    "minimumTier": True,
    "speaker": True,
    "category": True,
    "audience": True,
    "enableLivestream": True,
    "enableRecording": True,
    "nonMemberFee": True,
    "onlineURL": True,
    "materials": True,
    "videoURL": True,
    "eventMedia": True,
    "notes": True,
    "slug": True,
    "_status": True,
}
```

禁止選取 `checkIns`、Users、Memberships、account、session、token 或其他非顯示用途欄位。若 `eventMedia` 在 `depth=0` 只回傳 ID，repository 應使用專用的公開 media projection 或 website 產生的公開 URL 欄位，不可為取得圖片而提高整個 Event query 的 depth。

### 10.2 Repository API

```python
async def find_by_id(event_id: int) -> Event | None
async def list_published(
    *,
    starts_at_or_after: datetime | None = None,
    starts_before: datetime | None = None,
) -> list[Event]
```

行為：

- 永遠加入 `{"_status": {"equals": "published"}}`。
- `find_by_id` 使用 `id`，並再次驗證 `_status`，不得回傳 draft。
- 日期 query 使用 ISO 8601 UTC boundary。
- 每頁 `limit=100`，從 `page=1` 開始，直到回傳少於 100 筆。
- 結果固定依 `startDate`、`id` 排序，避免相同時間順序不穩定。
- 任一 document 違反 schema 時整次操作 fail closed，不默默略過壞資料。
- 不在 repository 實作 viewer tier、中文格式化或通知邏輯。

查詢台北某日活動時，service 先建立半開區間，再交給 repository：

```text
[2026-08-01 00:00:00+08:00, 2026-08-02 00:00:00+08:00)
```

轉成 UTC 後使用 Payload `greater_than_equal` 與 `less_than` operator 查詢 `startDate`。

## 11. EventService

Event use case 位於 `src/ian/application/events.py`，負責 use case 與權限：

```python
async def get_event(event_id: int, viewer_tier: int) -> Event | None
async def list_events_on_date(target_date: date, viewer_tier: int) -> list[Event]
async def list_upcoming_events(viewer_tier: int, limit: int = 3) -> list[Event]
async def search_events(query: str, viewer_tier: int) -> list[Event]
async def get_published_event_for_staff(event_id: int) -> Event | None
def can_access(event: Event, viewer_tier: int) -> bool
def format_event(event: Event) -> str
def format_events(events: list[Event]) -> str
```

規則：

- 一律先過濾 `viewer_tier >= event.required_tier`，再執行格式化。
- 不向無權限使用者透露受限 Event 的 title、日期或存在與否。
- 日期搜尋支援 `YYYY-MM-DD`、`YYYY/MM/DD` 與 `MM/DD`，最後轉成 `date`。
- 文字搜尋涵蓋 `title`、`speaker`、`category`、`audience`、`location`、Lexical plaintext、`notes` 與 material label。
- 查詢結果依 `startDate`、`id` 排序。
- 第一版不使用本地 disk cache 或 stale fallback；每次 use case 以 MCP 為準。
- 若未來需要 cache，必須另行定義 TTL、失效、schema version 與敏感資料邊界。

MemberService 增加：

```python
async def get_member_tier(platform: str, account_id: str) -> MemberTier
```

找不到 user、無有效 membership 或 MCP 失敗時，此方法回傳 tier 0；但 MCP failure 必須記錄成 dependency failure，不能偽裝成正常 not-found。

## 12. Consumer 改動

### 12.1 Event Retriever

- 將 typo tool `course_retreviler` 改名為 `event_retriever`，不保留舊 tool alias。
- 保留 `platform`、`account_id`、`query`；移除用來繞過權限的 `channel_id` 判斷。
- 先呼叫 `MemberService.get_member_tier()`，再呼叫 `EventService.search_events()`。
- 空 query 回傳使用者可見的近期 Events，不下載所有歷史資料。
- Agent prompt、tool allowlist、架構文件與測試同步使用 `event_retriever`。
- Event MCP error 回傳一般性暫時不可用訊息；不得包含 MCP response、URL、API key 或內容資料。

### 12.2 Daily Event Reminder

移除 `fetch_course_data()` 與 pandas `find_events_on_date()`，流程改為：

1. 以 `Asia/Taipei` 計算目標日期。
2. `EventService.list_events_on_date(target_date, viewer_tier=3)` 取得當日所有 published Events；這裡 tier 3 只代表先取得完整候選集合。
3. 從 `MemberService.list_reminder_recipients()` 取得已訂閱的有效社員。
4. 對每位 recipient，依其 `tier` 過濾可見 Events。
5. recipient 沒有可見 Event 時不發送。
6. 將該 recipient 可見的所有 Events 合併成一則提醒，避免同日多場活動重複 DM。
7. 沿用現有單一 `subscribe` 平台與簽到碼行為。

不能先把所有 Events 格式化成同一則訊息再群發，否則 tier 1 可能收到 minimum tier 2/3 的內容。

### 12.3 notify_members

新介面：

```python
async def notify_members(
    role: str,
    event_id: int | None = None,
    note: str = "",
    custom_message: str = "",
) -> str:
```

活動通知模式：

1. 沒有 `event_id` 與 `custom_message` 時，列出近期三場 published Events，必須顯示 `id`、title、台北日期時間與 location。
2. 幹部傳入 `event_id` 後，以 `get_published_event_for_staff()` 精確取得活動。
3. 依 Event `minimumTier` 過濾 reminder recipients。
4. 格式化單一 Event 並發送。
5. log 只記錄 `event_id`、required tier、recipient/success/failure count。

自訂通知模式維持現況：不套用 Event `minimumTier`，發給所有有效且已設定單一 `subscribe` 平台的 recipients。

移除 `_find_event_by_date()`；日期不得再作為活動通知主鍵。

## 13. 格式化規格

Event 顯示順序固定：

1. `title`
2. 台北日期與星期
3. 台北開始／結束時間
4. `location`
5. `speaker`
6. `category`
7. `audience`
8. Lexical `content` plaintext
9. 直播／錄影狀態
10. `nonMemberFee`
11. `onlineURL`
12. `materials`
13. `videoURL`
14. `eventMedia`
15. `notes`

空值不顯示，不再輸出「尚未上傳」。所有 Event 是否可見由 `minimumTier` 決定，不再維護 `MEMBER_ONLY_FIELDS` 欄位級規則。

## 14. 錯誤與安全策略

| 情境 | 行為 |
| --- | --- |
| MCP timeout／連線失敗 | 回傳 dependency unavailable；不讀 CSV，不使用 stale cache |
| MCP 401／403 | configuration failure；記錄 error type，不記錄 key |
| tool 回傳 error | `EventToolError` |
| JSON 無法解析 | `EventSchemaError` |
| published Event 缺 required field | 整次 query fail closed，要求修正 website 資料 |
| 同日多場 Event | 全部回傳；使用 `id` 選擇特定活動 |
| Member MCP failure | viewer tier 0；受限 Event 不可見 |
| 無權限 Event ID | 對一般使用者表現為 not found |
| draft Event | 永不回傳、搜尋或通知 |

URL 顯示前必須驗證 scheme；log 不記錄 Event content、notes、online URL、material URL、使用者帳號或 notification message。

## 15. Observability

Event repository／service 至少記錄：

- tool name
- operation（find by id、list date、upcoming、search）
- page count 與 record count
- date range
- duration
- status 與 error type
- `event_id`（只有精確查詢時）
- required tier 與過濾後數量

不得記錄：API key、MCP raw response、Lexical content、notes、URLs、recipient identity。

## 16. 程式與檔案變更

### 新增

- `src/ian/domain/events.py`
- `src/ian/infrastructure/payload_mcp/client.py`
- `src/ian/infrastructure/payload_mcp/event_repository.py`
- `src/ian/application/events.py`
- `tests/domain/test_events.py`
- `tests/services/test_payload_mcp_client.py`
- `tests/services/test_event_mcp_repository.py`
- `tests/services/test_event_service.py`

### 修改

- `src/ian/config.py`
- `src/ian/domain/reminders.py`
- `src/ian/infrastructure/payload_mcp/member_repository.py`
- `src/ian/application/members.py`
- `src/ian/services/reminder_runner.py`
- `src/ian/infrastructure/notifications/adapters.py`
- `src/ian/gateways/mcp_server.py`
- `src/ian/infrastructure/agent/prompt.py`
- `.env.example`
- `ARCHITECTURE.md`
- `CONTRIBUTION.md`
- `pyproject.toml`
- `uv.lock`
- 對應 gateway、reminder、config 與 logging tests

### 移除

- `src/ian/domain/courses.py`
- `src/ian/services/course_catalog.py`
- `tests/domain/test_courses.py`
- `tests/services/test_course_catalog.py`
- `COURSE_DATA_URL`
- 課程專用 `course_data.csv` 與 timestamp cache 邏輯
- `pandas` dependency（遷移後 production 與 tests 均無其他使用者）

`requests` 仍由通知與平台 adapters 使用，不移除。共用 `CACHE_DIR` 仍由 RAG 使用，也不移除。

## 17. 測試計畫

### Domain tests

- aware datetime、UTC/Taipei 轉換與跨日活動
- `endDate >= startDate`
- minimum tier 0–3 與 `null`
- title trim 與 required validation
- URL scheme validation
- materials/media schema
- Lexical paragraph、heading、list、link、未知 node、空 document
- 格式化順序與空值省略

### Repository tests

- 固定 `depth=0` 與 `EVENT_SELECT`
- `_status=published` 永遠存在
- `id` 精確查詢
- 日期 `greater_than_equal`／`less_than` boundary
- 100 筆分頁、剛好 100 筆、最後空頁
- deterministic sort
- zero documents
- MCP timeout、tool error、invalid JSON、invalid document
- draft leakage 防護
- `checkIns` 不在 select 與 model

### Service tests

- tier 0 可見 public Event
- tier 1/2/3 門檻矩陣
- 無權限 Event 表現為 not found
- 日期、日期範圍與文字搜尋
- 同日多 Events
- upcoming limit 與排序
- Member MCP failure 時 fail closed

### Consumer tests

- `event_retriever` 使用 MemberService tier
- 白名單 channel 不繞過 minimum tier
- reminder 依每位 recipient tier 產生不同 Event 集合
- reminder 同日多 Event 合併一次發送
- `notify_members(event_id=...)` 精確選擇
- 活動通知 recipient tier 過濾
- custom message 不套 Event tier
- dry run、partial delivery failure 與 sanitized logging

### Live smoke test

使用 read-only MCP key：

1. 列出 tools 並確認 `findEvents` 存在。
2. 以 `depth=0`、`select`、published filter 讀取所有分頁。
3. 驗證 published Events 的 required fields。
4. 驗證 minimum tier 只包含 `null`、0、1、2、3。
5. 驗證 draft 不會進入 repository 結果。
6. 以已知 Event ID 測試精確查詢。
7. 執行 reminder `--dry`，不發出外部通知。

## 18. 實作階段與 Commit 切分

### Phase 0：ntuai.dev schema 與資料就緒

- 新增／調整第 7 節欄位。
- 修正 3 筆缺 title 的 published Events。
- 設定 Ian API key 最小權限。
- 執行 publish validation 與資料 audit。

完成條件：website contract 與 required data 通過，`findEvents` 可讀取所有 allowlist 欄位。

### Phase 1：共用 MCP transport 與 Event domain

- 抽出 `payload_mcp_client.py`。
- 新增 Event models、Lexical plaintext converter 與 repository。
- 保持 MemberService tests 全數通過。

建議 commit：`[Refactor]: share ntuai.dev MCP transport`

### Phase 2：Event service 與搜尋

- 新增 EventService。
- 新增 tier access、date/upcoming/search/formatting。
- 將 `course_retreviler` 替換為 `event_retriever`。

建議 commit：`[Feat]: source event retrieval from ntuai.dev MCP`

### Phase 3：提醒與社員通知

- Reminder Runner 改用 EventService。
- 每位 recipient 套用 Event minimum tier。
- `notify_members` 改用 `event_id`。

建議 commit：`[Feat]: source event notifications from ntuai.dev MCP`

### Phase 4：移除 CSV 與 pandas

- 刪除 course catalog、DataFrame domain 與舊 tests。
- 移除環境變數、cache 與 pandas dependency。
- 更新 architecture、contribution 與 agent prompt。

建議 commit：`[Refactor]: remove local course data source`

### Phase 5：整合驗證

- 完整 unit/integration tests。
- live read-only smoke test。
- reminder dry run。
- 啟動 MCP server 驗證 tools。

建議 commit：`[Test]: cover Event MCP integration boundaries`

## 19. Rollback

專案尚未上線，rollback 只採 Git／deployment revert：

- Phase 1–3：revert 對應 commits。
- Phase 4 之後：revert 整個 Event MCP PR。
- 不在 production code 重新加入 CSV fallback。
- ntuai.dev 新增的選填欄位可保留；Ian 對 Events 沒有寫入，因此不會產生資料回滾問題。

## 20. 驗收條件

- [ ] ntuai.dev Event schema 包含第 7 節欄位。
- [ ] 所有 published Events 的 title、startDate、endDate、slug 有效。
- [ ] Ian 只透過 `EventMcpRepository` 讀取 Events。
- [ ] 一般查詢與活動通知均正確套用 `minimumTier`。
- [ ] `notify_members` 以 `event_id` 選擇活動。
- [ ] reminder 對每位 recipient 過濾可見 Events。
- [ ] draft 與 `checkIns` 不會進入 Ian domain 或 log。
- [ ] `COURSE_DATA_URL`、course CSV cache、pandas course code 全部移除。
- [ ] repository、service、gateway、reminder tests 通過。
- [ ] `uv run ruff check .` 與 `uv run pytest` 通過。
- [ ] live smoke test 與 reminder dry run 通過。

## 21. 官方技術依據

- Payload query operators：<https://payloadcms.com/docs/queries/overview>
- Payload Rich Text field：<https://payloadcms.com/docs/fields/rich-text>
- Payload Lexical converters：<https://payloadcms.com/docs/rich-text/converters>
