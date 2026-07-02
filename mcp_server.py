import warnings
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")

from mcp.server.fastmcp import FastMCP
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

import asyncio, os, sys, json, math, re, time, hashlib, io, threading
from datetime import datetime, timedelta, timezone
import pandas as pd
import jieba
import jieba.analyse
import requests
from typing import List, Dict, Any, Tuple, Optional
from collections import Counter
from functools import lru_cache

from member_db import (
    bind_email as _bind_email_to_platform,
    find_member_by_email,
    lookup_member_by_platform,
    get_member_role,
    update_subscribe as _update_subscribe,
    update_personal_prompt as _update_personal_prompt,
    init as init_member_db,
)


def eprint(*args, **kwargs):
    """Print to stderr to avoid interfering with MCP stdio transport."""
    print(*args, file=sys.stderr, **kwargs)


# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------
MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "5191"))
mcp = FastMCP(host=MCP_HOST, port=MCP_PORT, stateless_http=True)

# ---------------------------------------------------------------------------
# Global RAG components
# ---------------------------------------------------------------------------
vector_store = None
embedding_model = None
llm = None
documents = []
bm25_system = None
bm25_corpus = []
bm25_docs = []

# ---------------------------------------------------------------------------
# Course data (Google Sheets CSV)
# ---------------------------------------------------------------------------
course_data = None
course_data_url = os.environ.get("COURSE_DATA_URL", "")
last_course_update = None
course_update_interval = 0.5 * 60 * 60  # 0.5 hour

# ---------------------------------------------------------------------------
# Cache paths
# ---------------------------------------------------------------------------
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
COURSE_CACHE_FILE = os.path.join(CACHE_DIR, "course_data.csv")
COURSE_CACHE_TIMESTAMP_FILE = os.path.join(CACHE_DIR, "course_data_timestamp.txt")

# FAISS 索引快取路徑
FAISS_INDEX_DIR = os.path.join(CACHE_DIR, "faiss_index")
FAISS_HASH_FILE = os.path.join(CACHE_DIR, "faiss_source_hash.txt")

# ---------------------------------------------------------------------------
# Permission control
# ---------------------------------------------------------------------------
NON_MEMBER_PREFIX = "非社員"
MEMBER_ONLY_FIELDS = ["線上連結", "錄影檔案", "課程照片", "課程講義", "備註"]
# Discord Channel IDs 具有完整權限（從 .env 讀取）
ALLOWED_DISCORD_CHANNELS = [c.strip() for c in os.environ.get("DISCORD_ALLOWED_CHANNELS", "").split(",") if c.strip()]
# LINE 白名單群組也具有完整權限（從 .env 讀取，自動同步）
LINE_ALLOWED_GROUPS = [g.strip() for g in os.environ.get("LINE_ALLOWED_GROUPS", "").split(",") if g.strip()]
ALLOWED_CHANNELS = ALLOWED_DISCORD_CHANNELS + LINE_ALLOWED_GROUPS


class SimpleBM25:
    def __init__(self, corpus, k1=1.5, b=0.75):
        self.corpus = corpus
        self.k1 = k1
        self.b = b
        self.doc_len = [len(doc) for doc in corpus]
        self.avgdl = sum(self.doc_len) / len(self.doc_len) if corpus else 0
        self.doc_freqs = []
        self.idf = {}
        self.doc_count = len(corpus)

        df = {}
        for doc in corpus:
            freq = {}
            for word in doc:
                freq[word] = freq.get(word, 0) + 1
            self.doc_freqs.append(freq)

            for word in freq.keys():
                df[word] = df.get(word, 0) + 1

        for word, freq in df.items():
            self.idf[word] = math.log((self.doc_count - freq + 0.5) / (freq + 0.5))

    def get_scores(self, query):
        scores = []
        for i, doc_freq in enumerate(self.doc_freqs):
            score = 0
            doc_len = self.doc_len[i]

            for word in query:
                if word in doc_freq:
                    tf = doc_freq[word]
                    idf = self.idf.get(word, 0)
                    score += (
                        idf
                        * (tf * (self.k1 + 1))
                        / (tf + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl))
                    )

            scores.append(score)
        return scores

def check_user_permission(
    platform: Optional[str] = None,
    account_id: Optional[str] = None,
    channel_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """Return (has_permission, role) for the user.

    Role is looked up from the bound member DB (NOT from any role string passed
    by the caller / LLM). Permission is granted when:
      - the user is in an allowed channel, OR
      - the user's bound member record is valid (role does not start with 非社員).

    Returns the resolved role string for logging / downstream use.
    """
    role = "非社員"
    if platform and account_id:
        role = get_member_role(platform, str(account_id).strip())

    if channel_id and channel_id in ALLOWED_CHANNELS:
        return True, role
    if role and not role.startswith(NON_MEMBER_PREFIX):
        return True, role
    return False, role

def _get_cache_timestamp() -> float:
    """讀取快取時間戳記"""
    try:
        if os.path.exists(COURSE_CACHE_TIMESTAMP_FILE):
            with open(COURSE_CACHE_TIMESTAMP_FILE, 'r') as f:
                return float(f.read().strip())
    except (ValueError, IOError):
        pass
    return 0

def _save_cache_timestamp(timestamp: float):
    """儲存快取時間戳記"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(COURSE_CACHE_TIMESTAMP_FILE, 'w') as f:
        f.write(str(timestamp))

def _is_cache_valid() -> bool:
    """檢查快取是否有效（未過期且檔案存在）"""
    if not os.path.exists(COURSE_CACHE_FILE):
        return False
    cache_timestamp = _get_cache_timestamp()
    current_time = time.time()
    return (current_time - cache_timestamp) < course_update_interval

def _load_from_cache() -> pd.DataFrame:
    """從快取檔案載入課程資料"""
    global course_data, last_course_update
    try:
        df = pd.read_csv(COURSE_CACHE_FILE)
        course_data = df
        last_course_update = _get_cache_timestamp()
        eprint(f"[快取] 從本地快取載入課程資料，共 {len(df)} 筆記錄")
        return df
    except Exception as e:
        eprint(f"[快取] 讀取快取失敗: {e}")
        return None

def _save_to_cache(df: pd.DataFrame, timestamp: float):
    """將課程資料儲存到快取檔案"""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        df.to_csv(COURSE_CACHE_FILE, index=False, encoding='utf-8')
        _save_cache_timestamp(timestamp)
        eprint(f"[快取] 課程資料已儲存到本地快取")
    except Exception as e:
        eprint(f"[快取] 儲存快取失敗: {e}")

def _fetch_from_url(url: str, max_retries: int = 3) -> pd.DataFrame:
    """從網路載入課程資料"""
    for attempt in range(max_retries):
        try:
            eprint(f"[網路] 正在從 Google Sheets 載入課程資料... (嘗試 {attempt + 1}/{max_retries})")

            # 設定請求標頭以避免被阻擋
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }

            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            response.encoding = "utf-8"

            csv_data = io.StringIO(response.text)
            df = pd.read_csv(csv_data)

            if any(r"\x" in str(col) for col in df.columns): # Check for encoding artifacts in columns
                eprint("偵測到編碼問題，嘗試修復...")
                try:
                    response_bytes = requests.get(
                        url, headers=headers, timeout=30
                    ).content

                    for encoding in ["utf-8", "utf-8-sig", "big5", "gb2312"]:
                        try:
                            decoded_text = response_bytes.decode(encoding)
                            csv_data = io.StringIO(decoded_text)
                            df = pd.read_csv(csv_data)

                            if not any(r"\x" in str(col) for col in df.columns):
                                eprint(f"編碼修復成功，使用編碼: {encoding}")
                                break
                        except (UnicodeDecodeError, UnicodeError):
                            continue
                    else:
                        eprint("無法自動修復編碼問題")
                except Exception as e:
                    eprint(f"編碼修復失敗: {e}")

            eprint(f"[網路] 課程資料載入成功，共 {len(df)} 筆記錄")
            return df

        except requests.exceptions.RequestException as e:
            eprint(f"網路請求錯誤 (嘗試 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2**attempt)  # 指數退避
        except pd.errors.EmptyDataError as e:
            eprint(f"CSV 資料為空 (嘗試 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
        except pd.errors.ParserError as e:
            eprint(f"CSV 解析錯誤 (嘗試 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
        except Exception as e:
            eprint(f"載入課程資料時發生未預期錯誤 (嘗試 {attempt + 1}/{max_retries}): {type(e).__name__} - {e}")
            if attempt < max_retries - 1:
                time.sleep(2**attempt)

    eprint(f"[網路] 所有嘗試均失敗，無法載入課程資料")
    return None

def load_course_data_from_url(url: str, max_retries: int = 3) -> pd.DataFrame:
    """
    載入課程資料（帶快取機制）
    1. 先檢查本地快取是否有效（未過期）
    2. 如果快取有效，直接從快取載入
    3. 如果快取過期或不存在，從網路載入並更新快取
    """
    global course_data, last_course_update

    # 檢查快取是否有效
    if _is_cache_valid():
        return _load_from_cache()

    if not url:
        eprint("[設定] COURSE_DATA_URL is not configured")
        if os.path.exists(COURSE_CACHE_FILE):
            eprint("[快取] 使用過期的本地快取")
            return _load_from_cache()
        return None
    
    # 快取無效，從網路載入
    df = _fetch_from_url(url, max_retries)
    
    if df is not None:
        current_time = time.time()
        course_data = df
        last_course_update = current_time
        _save_to_cache(df, current_time)
        return df
    
    # 網路載入失敗，嘗試使用過期的快取
    if os.path.exists(COURSE_CACHE_FILE):
        eprint("[快取] 網路載入失敗，使用過期的本地快取")
        return _load_from_cache()
    
    return None


# 以下更新執行緒相關函數已棄用，改用檔案快取機制

def get_column_mapping(df: pd.DataFrame) -> Dict[str, str]:
    """建立欄位名稱對應表，處理可能的編碼問題"""
    column_mapping = {}
    
    for col in df.columns:
        original_col = str(col)
        # 如果欄位名稱包含編碼錯誤字符，嘗試修復或使用通用名稱
        if r"\x" in original_col:
            # 根據位置推測欄位名稱
            col_index = list(df.columns).index(col)
            common_names = [
                "週次",
                "時間",
                "星期",
                "活動時間",
                "場地",
                "是否直播",
                "是否錄影",
                "社課主題/活動名稱",
                "講者",
                "社課類別",
                "課程大綱",
                "課程對象",
                "非社員報名費用",
                "線上連結",
                "錄影檔案",
                "課程照片",
                "課程講義",
                "備註",
            ]
            if col_index < len(common_names):
                column_mapping[col] = common_names[col_index]
            else:
                column_mapping[col] = f"欄位{col_index + 1}"
        else:
            column_mapping[col] = original_col
    
    return column_mapping


def format_course_data(df: pd.DataFrame, has_permission: bool) -> str:
    """格式化課程資料，根據權限過濾敏感欄位"""
    if df is None or df.empty:
        return "課程資料無法載入或為空"

    formatted_content = []
    column_mapping = get_column_mapping(df)

    for index, row in df.iterrows():
        course_info = []

        # 將每一列的所有非空值加入課程資訊
        for col in df.columns:
            value = row[col]
            friendly_col_name = column_mapping.get(col, str(col))
            has_value = pd.notna(value) and str(value).strip()

            if has_value:
                # 檢查使用者是否有權限存取敏感欄位
                if not has_permission and friendly_col_name in MEMBER_ONLY_FIELDS:
                    continue

                course_info.append(f"{friendly_col_name}: {value}")
            elif has_permission and friendly_col_name in MEMBER_ONLY_FIELDS:
                # 有權限但欄位為空：明確標示尚未上傳，避免 LLM 自行捏造連結
                course_info.append(f"{friendly_col_name}: (尚未上傳)")

        if course_info:
            course_content = f"=== 課程記錄 {index + 1} ===\n" + "\n".join(course_info)
            formatted_content.append(course_content)

    return "\n\n".join(formatted_content)


TZ_TPE = timezone(timedelta(hours=8))

# Regex for dates: YYYY/MM/DD, YYYY-MM-DD, or M/D, MM/DD
_DATE_FULL_RE = re.compile(r'(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})')
_DATE_SHORT_RE = re.compile(r'^(\d{1,2})[/\-](\d{1,2})$')


def _normalize_date(year: int, month: int, day: int) -> str:
    """Return date as YYYY/MM/DD (zero-padded), matching CSV format."""
    return f"{year:04d}/{month:02d}/{day:02d}"


def _parse_dates_from_query(query: str) -> list[str]:
    """Extract normalized YYYY/MM/DD dates from query string.

    Handles: YYYY/MM/DD, YYYY-MM-DD, M/D (uses current year).
    """
    now = datetime.now(TZ_TPE)
    dates = []
    for m in _DATE_FULL_RE.finditer(query):
        dates.append(_normalize_date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    if not dates:
        m = _DATE_SHORT_RE.match(query.strip())
        if m:
            dates.append(_normalize_date(now.year, int(m.group(1)), int(m.group(2))))
    return dates


def _get_date_column(df: pd.DataFrame) -> str | None:
    """Find the date column name (handles encoding issues)."""
    mapping = get_column_mapping(df)
    for col, friendly in mapping.items():
        if friendly == "時間":
            return col
    return None


def _get_upcoming_courses(has_permission: bool, weeks: int = 2) -> str:
    """Return courses within the next N weeks from today."""
    global course_data
    if course_data is None or course_data.empty:
        return ""
    date_col = _get_date_column(course_data)
    if date_col is None:
        return ""
    now = datetime.now(TZ_TPE)
    today_str = _normalize_date(now.year, now.month, now.day)
    end = now + timedelta(weeks=weeks)
    end_str = _normalize_date(end.year, end.month, end.day)
    matching = []
    for idx, row in course_data.iterrows():
        d = str(row.get(date_col, "")).strip()
        if today_str <= d <= end_str:
            matching.append(idx)
    if not matching:
        return ""
    matched_data = course_data.iloc[matching]
    formatted = format_course_data(matched_data, has_permission)
    return f"近期課程（未來 {weeks} 週），共 {len(matching)} 筆：\n\n{formatted}"


def search_course_data_by_query(query: str, has_permission: bool) -> Tuple[bool, str]:
    """在課程資料中搜尋相關內容，返回是否找到匹配結果和格式化結果"""
    global course_data

    if course_data is None or course_data.empty:
        return False, "課程資料尚未載入或為空，請稍後再試"

    try:
        date_col = _get_date_column(course_data)
        parsed_dates = _parse_dates_from_query(query)

        # Date-aware search
        if parsed_dates and date_col is not None:
            matching_rows = []
            if len(parsed_dates) == 1:
                target = parsed_dates[0]
                for idx, row in course_data.iterrows():
                    if str(row.get(date_col, "")).strip() == target:
                        matching_rows.append(idx)
            else:
                start, end = sorted(parsed_dates[:2])
                for idx, row in course_data.iterrows():
                    d = str(row.get(date_col, "")).strip()
                    if start <= d <= end:
                        matching_rows.append(idx)
            if matching_rows:
                matched_data = course_data.iloc[matching_rows]
                formatted_data = format_course_data(matched_data, has_permission)
                return True, f"找到 {len(matching_rows)} 筆課程資料：\n\n{formatted_data}"

        # Text search fallback
        query_lower = query.lower()
        matching_rows = []

        for index, row in course_data.iterrows():
            row_text = " ".join(
                [str(val) for val in row.values if pd.notna(val)]
            ).lower()
            if query_lower in row_text:
                matching_rows.append(index)

        if matching_rows:
            matched_data = course_data.iloc[matching_rows]
            formatted_data = format_course_data(matched_data, has_permission)
            return True, f"找到 {len(matching_rows)} 筆包含 '{query}' 的課程資料：\n\n{formatted_data}"
        else:
            return False, ""

    except Exception as e:
        return False, f"搜尋課程資料時發生錯誤: {str(e)}"


def get_all_course_data(has_permission: bool) -> str:
    """取得所有課程資料"""
    global course_data
    
    if course_data is None or course_data.empty:
        return "目前沒有任何課程資料"
    
    formatted_data = format_course_data(course_data, has_permission)
    return f"所有課程資料，共 {len(course_data)} 筆：\n\n{formatted_data}"


def get_permission_notice(has_permission: bool) -> str:
    """根據權限返回提示語"""
    if not has_permission:
        return f"\n\n💡 注意：目前無法獲取您的社員狀態，因此無法取得{', '.join(MEMBER_ONLY_FIELDS)}等內容。"
    return ""

@lru_cache(maxsize=10)
def load_jsonl_data(file_path: str) -> List[Dict[str, Any]]:
    """載入 JSONL 檔案"""
    data = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    data.append(json.loads(line))
    except FileNotFoundError:
        eprint(f"檔案不存在: {file_path}")
    except Exception as e:
        eprint(f"載入 JSONL 檔案錯誤: {e}")
    return data

@lru_cache(maxsize=10)
def load_markdown_data(file_path: str) -> str:
    """載入 Markdown 檔案"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        eprint(f"檔案不存在: {file_path}")
        return ""
    except Exception as e:
        eprint(f"載入 Markdown 檔案錯誤: {e}")
        return ""


def extract_keywords(text: str, top_k: int = 5) -> List[str]:
    """使用 jieba TF-IDF 提取關鍵字。"""
    try:
        keywords = jieba.analyse.extract_tags(text, topK=top_k, withWeight=False)
        return keywords
    except:
        # 如果 jieba 失敗，使用簡單方法
        words = re.findall(r"[\u4e00-\u9fff]+", text)
        word_freq = Counter(words)
        return [word for word, _ in word_freq.most_common(top_k) if len(word) > 1]


def create_enhanced_documents(
    jsonl_data: List[Dict], md_content: str
) -> List[Document]:
    """創建增強的文檔"""
    documents = []

    # 處理 JSONL 資料
    for item in jsonl_data:
        if item.get("type") == "faq":
            question = item.get("question", "").strip()
            answer = item.get("answer", "").strip()

            if question and answer:
                content = f"問題：{question}\n答案：{answer}"
                keywords = extract_keywords(question + " " + answer)
                if keywords:
                    content += f"\n關鍵字：{', '.join(keywords)}"

                metadata = {
                    "source": "faq",
                    "id": item.get("id", ""),
                    "type": "faq",
                    "question": question,
                    "answer": answer,
                    "tags": item.get("tags", []),
                    "keywords": keywords,
                }
                documents.append(Document(page_content=content, metadata=metadata))

        elif item.get("type") == "paragraph":
            content = item.get("text", "").strip()
            if content:
                path = item.get("path", "未分類")
                enhanced_content = f"分類：{path}\n內容：{content}"
                keywords = extract_keywords(content)
                if keywords:
                    enhanced_content += f"\n關鍵字：{', '.join(keywords)}"

                metadata = {
                    "source": "paragraph",
                    "id": item.get("id", ""),
                    "path": path,
                    "type": "paragraph",
                    "keywords": keywords,
                }
                documents.append(
                    Document(page_content=enhanced_content, metadata=metadata)
                )

        elif item.get("type") == "entity":
            entity_type = item.get("entity_type", "")
            name = item.get("name", "")
            content_parts = [f"實體類型：{entity_type}", f"名稱：{name}"]

            if entity_type == "membership_fee":
                fees = item.get("fees", {})
                content_parts.extend(
                    [
                        f"社費 學期費用 {fees.get('semester_fee', '')}元",
                        f"社費 學年費用 {fees.get('year_fee', {}).get('amount', '')}元",
                        f"社費 終身費用 {fees.get('lifetime_fee', '')}元",
                        "繳費 報名 加入社團 收費 費用",
                    ]
                )
            elif entity_type == "contact":
                emails = item.get("emails", [])
                urls = item.get("urls", [])
                content_parts.extend(
                    [
                        f"聯絡方式 email 信箱：{', '.join(emails)}",
                        f"社群 連結 網站：{', '.join(urls)}",
                        "聯繫 聯絡 contact 找到 聯繫方式",
                    ]
                )
            elif entity_type == "course_schedule":
                content_parts.extend(
                    [
                        "社課時間 上課時間 星期四 週四 晚上 7點 9點",
                        "時間 schedule 課程安排 什麼時候 幾點",
                    ]
                )

            content = "\n".join(content_parts)
            keywords = extract_keywords(content)

            metadata = {
                "source": "entity",
                "id": item.get("id", ""),
                "type": "entity",
                "entity_type": entity_type,
                "keywords": keywords,
            }
            documents.append(Document(page_content=content, metadata=metadata))

    # 處理 Markdown
    if md_content:
        sections = re.split(r"\n(?=#{1,3}\s)", md_content)

        for i, section in enumerate(sections):
            if section.strip():
                lines = section.strip().split("\n")
                title_line = lines[0] if lines else ""
                title = re.sub(r"^#{1,3}\s*", "", title_line).strip()

                if len(section) > 1000:
                    text_splitter = RecursiveCharacterTextSplitter(
                        chunk_size=600,
                        chunk_overlap=100,
                        separators=["\n\n", "\n", "。", "！", "？"],
                    )
                    chunks = text_splitter.split_text(section)

                    for j, chunk in enumerate(chunks):
                        if chunk.strip():
                            keywords = extract_keywords(chunk)
                            content = f"章節：{title}\n內容：{chunk.strip()}"
                            if keywords:
                                content += f"\n關鍵字：{', '.join(keywords)}"

                            metadata = {
                                "source": "markdown",
                                "section_title": title,
                                "chunk_id": f"{i}_{j}",
                                "type": "markdown_chunk",
                                "keywords": keywords,
                            }
                            documents.append(
                                Document(page_content=content, metadata=metadata)
                            )
                else:
                    keywords = extract_keywords(section)
                    content = f"章節：{title}\n內容：{section.strip()}"
                    if keywords:
                        content += f"\n關鍵字：{', '.join(keywords)}"

                    metadata = {
                        "source": "markdown",
                        "section_title": title,
                        "chunk_id": str(i),
                        "type": "markdown_section",
                        "keywords": keywords,
                    }
                    documents.append(Document(page_content=content, metadata=metadata))
    return documents


def build_bm25_index():
    """建立 BM25 索引"""
    global bm25_system, bm25_corpus, bm25_docs, documents
    bm25_docs = []
    bm25_corpus = []
    for doc in documents:
        # 分詞
        tokens = list(jieba.cut(doc.page_content))
        tokens = [
            token.strip()
            for token in tokens
            if token.strip() and len(token.strip()) > 1
        ]

        bm25_corpus.append(tokens)
        bm25_docs.append(doc)

    bm25_system = SimpleBM25(bm25_corpus)
    eprint(f"BM25 索引建立完成: {len(bm25_corpus)} 個文檔")


def bm25_search(query: str, top_k: int = 10) -> List[Tuple[Document, float]]:
    """BM25 關鍵字搜尋"""
    if not bm25_system:
        return []

    query_tokens = list(jieba.cut(query))
    query_tokens = [
        token.strip()
        for token in query_tokens
        if token.strip() and len(token.strip()) > 1
    ]

    if not query_tokens:
        return []

    scores = bm25_system.get_scores(query_tokens)
    doc_scores = [(bm25_docs[i], scores[i]) for i in range(len(scores))]
    doc_scores.sort(key=lambda x: x[1], reverse=True)

    return doc_scores[:top_k]


def semantic_search(query: str, top_k: int = 10) -> List[Tuple[Document, float]]:
    """語意向量搜尋"""
    if not vector_store:
        return []
    return vector_store.similarity_search_with_score(query, k=top_k)


def hybrid_search(
    query: str, top_k: int = 5, alpha: float = 0.6,
) -> List[Tuple[Document, float, str]]:
    """混合搜尋"""
    # BM25 搜尋
    bm25_results = bm25_search(query, top_k * 2)

    # 語意搜尋
    semantic_results = semantic_search(query, top_k * 2)

    # 正規化分數
    def normalize_scores(results):
        if not results:
            return []
        scores = [score for _, score in results]
        min_score, max_score = min(scores), max(scores)
        if max_score == min_score:
            return [(doc, 0.5) for doc, _ in results]
        return [
            (doc, (score - min_score) / (max_score - min_score))
            for doc, score in results
        ]

    # 正規化分數
    norm_bm25 = normalize_scores(bm25_results)
    norm_semantic = [
        (doc, 1 - score) for doc, score in normalize_scores(semantic_results)
    ]

    doc_scores = {}

    # 加 BM25 結果
    for doc, score in norm_bm25:
        doc_id = doc.metadata.get("id", str(hash(doc.page_content)))
        doc_scores[doc_id] = {
            "doc": doc,
            "bm25_score": score,
            "semantic_score": 0,
            "methods": ["BM25"],
        }

    # 加語意搜尋結果
    for doc, score in norm_semantic:
        doc_id = doc.metadata.get("id", str(hash(doc.page_content)))
        if doc_id in doc_scores:
            doc_scores[doc_id]["semantic_score"] = score
            doc_scores[doc_id]["methods"].append("Semantic")
        else:
            doc_scores[doc_id] = {
                "doc": doc,
                "bm25_score": 0,
                "semantic_score": score,
                "methods": ["Semantic"],
            }

    # 計算混合分數
    final_results = []
    for doc_id, info in doc_scores.items():
        hybrid_score = alpha * info["bm25_score"] + (1 - alpha) * info["semantic_score"]
        methods_str = "+".join(info["methods"])
        final_results.append((info["doc"], hybrid_score, methods_str))

    # 排序並返回前 top_k 個結果
    final_results.sort(key=lambda x: x[1], reverse=True)
    return final_results[:top_k]


def _compute_source_hash(jsonl_path: str, md_path: str) -> str:
    """計算來源檔案的 hash，用於偵測文檔變更"""
    hasher = hashlib.md5()
    
    # 讀取 JSONL 檔案內容
    try:
        with open(jsonl_path, 'rb') as f:
            hasher.update(f.read())
    except FileNotFoundError:
        pass
    
    # 讀取 Markdown 檔案內容
    try:
        with open(md_path, 'rb') as f:
            hasher.update(f.read())
    except FileNotFoundError:
        pass
    
    return hasher.hexdigest()


def _get_saved_hash() -> str:
    """讀取已儲存的來源檔案 hash"""
    try:
        if os.path.exists(FAISS_HASH_FILE):
            with open(FAISS_HASH_FILE, 'r') as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


def _save_hash(hash_value: str):
    """儲存來源檔案 hash"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(FAISS_HASH_FILE, 'w') as f:
        f.write(hash_value)


def _try_load_faiss_index():
    """嘗試從快取載入 FAISS 索引"""
    global vector_store, embedding_model
    
    if not os.path.exists(FAISS_INDEX_DIR):
        return False
    
    try:
        vector_store = FAISS.load_local(
            FAISS_INDEX_DIR, 
            embedding_model,
            allow_dangerous_deserialization=True
        )
        eprint(f"[快取] 從本地快取載入 FAISS 索引")
        return True
    except Exception as e:
        eprint(f"[快取] 載入 FAISS 索引失敗: {e}")
        return False


def _save_faiss_index():
    """儲存 FAISS 索引到快取"""
    global vector_store
    
    try:
        os.makedirs(FAISS_INDEX_DIR, exist_ok=True)
        vector_store.save_local(FAISS_INDEX_DIR)
        eprint(f"[快取] FAISS 索引已儲存到本地快取")
    except Exception as e:
        eprint(f"[快取] 儲存 FAISS 索引失敗: {e}")


def _try_move_faiss_to_gpu():
    """嘗試將 FAISS 索引移到 GPU"""
    global vector_store
    
    try:
        import faiss as faiss_lib
        if faiss_lib.get_num_gpus() > 0:
            gpu_res = faiss_lib.StandardGpuResources()
            # 取得底層 FAISS 索引並轉移到 GPU
            cpu_index = vector_store.index
            gpu_index = faiss_lib.index_cpu_to_gpu(gpu_res, 0, cpu_index)
            vector_store.index = gpu_index
            eprint(f"[GPU] FAISS 索引已載入 GPU (共 {faiss_lib.get_num_gpus()} 個 GPU)")
            return True
        else:
            eprint("[GPU] 未偵測到可用的 GPU，使用 CPU 模式")
            return False
    except Exception as e:
        eprint(f"[GPU] 無法將 FAISS 索引移到 GPU: {e}")
        return False


def initialize_rag_system():
    """初始化 RAG 系統（帶快取機制）"""
    global vector_store, embedding_model, llm, documents

    # 初始化 jieba
    jieba.initialize()

    # 初始化嵌入模型
    try:
        embedding_model = HuggingFaceEmbeddings(
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        eprint("多語言嵌入模型初始化完成")
    except Exception as e:
        eprint(f"嵌入模型初始化失敗: {e}")
        return False

    # 來源檔案路徑
    jsonl_file_path = "./data/ntuai_recompiled_index.jsonl"
    md_file_path = "./data/ntuai_zh_base.md"

    try:
        # 計算來源檔案 hash
        current_hash = _compute_source_hash(jsonl_file_path, md_file_path)
        saved_hash = _get_saved_hash()
        
        # 檢查是否可以使用快取
        use_cache = (current_hash == saved_hash) and os.path.exists(FAISS_INDEX_DIR)
        
        if use_cache:
            eprint(f"[快取] 來源檔案未變更 (hash: {current_hash[:8]}...)，嘗試載入快取")
            if _try_load_faiss_index():
                # 快取載入成功，仍需載入文檔用於 BM25
                jsonl_data = load_jsonl_data(jsonl_file_path)
                md_content = load_markdown_data(md_file_path)
                documents = create_enhanced_documents(jsonl_data, md_content)
                build_bm25_index()
                _try_move_faiss_to_gpu()
                return True
            else:
                eprint("[快取] 快取載入失敗，重建索引")
        else:
            if saved_hash:
                eprint(f"[快取] 來源檔案已變更 (舊: {saved_hash[:8]}... → 新: {current_hash[:8]}...)，重建索引")
            else:
                eprint(f"[快取] 首次建立索引 (hash: {current_hash[:8]}...)")
        
        # 重建索引
        jsonl_data = load_jsonl_data(jsonl_file_path)
        md_content = load_markdown_data(md_file_path)
        documents = create_enhanced_documents(jsonl_data, md_content)
        
        if documents:
            vector_store = FAISS.from_documents(documents, embedding_model)
            eprint(f"向量資料庫建立完成, 包含 {len(documents)} 個文檔")
            
            # 儲存索引和 hash
            _save_faiss_index()
            _save_hash(current_hash)
            
            build_bm25_index()
            _try_move_faiss_to_gpu()
            return True
        else:
            eprint("沒有找到任何文檔資料")
            return False

    except Exception as e:
        eprint(f"初始化過程發生錯誤: {e}")
        return False

try:
    initialize_rag_system()
    load_course_data_from_url(course_data_url)
except Exception as e:
    eprint(f"初始化錯誤: {e}")

# Initialize member database
try:
    init_member_db()
    eprint("社員資料庫已初始化")
except Exception as e:
    eprint(f"社員資料庫初始化失敗: {e}")


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool(name="course_retreviler")
async def search_course_chunks_by_semantics(
    platform: str = "",
    account_id: str = "",
    query: str = "",
    channel_id: str = "",
) -> str:
    """
    根據使用者的問題意圖，檢索課程大綱或具體活動內容相關的資料（講義、照片、其他附件資料等），僅當問題屬於「課程」或「活動」時，才呼叫此工具。
    若使用者未指定活動內容，請優先回傳近期的活動資料概覽。

    權限控制：
    - 角色由系統自行查詢綁定資料庫判斷，不依賴呼叫方傳入的 role
    - 幹部 / 社員 / VIP 社員：可查看完整課程、活動資料
    - 非社員 / 未綁定者：僅可查看基本課程、活動資訊

    Args:
        platform: 使用者所在平台（Discord、FB、LINE），請從系統訊息中的 Platform 取得
        account_id: 使用者在該平台的帳號 ID，請從系統訊息中的 Account ID 取得
        query: 使用者問題查詢（非必要，需要透過明確的關鍵字來搜尋，像是：課程名稱關鍵字等，否則就留空）。日期請統一使用 YYYY/MM/DD 格式（例如 2026/03/26），查詢日期範圍請用空格分隔兩個日期（例如 2026/03/26 2026/03/30）。短日期如 3/26 也可接受。
        channel_id: 使用者所在的頻道 ID（白名單頻道內具完整權限）
    """
    try:
        # 確保課程資料已載入（會自動使用快取機制）
        # 使用 asyncio.to_thread 避免阻塞 event loop（requests.get / time.sleep 都是同步阻塞）
        await asyncio.to_thread(load_course_data_from_url, course_data_url)

        # 權限檢查 — 角色一律從綁定 DB 查，不採信 LLM 傳進來的字串
        has_permission, resolved_role = await asyncio.to_thread(
            check_user_permission, platform, account_id, channel_id
        )
        access_level = "完整權限" if has_permission else "受限權限"
        eprint(
            f"課程資料查詢 - 平台: {platform}, 帳號: {account_id}, "
            f"DB 角色: {resolved_role}, 頻道 ID: {channel_id}, "
            f"權限: {access_level}, 查詢: {query}"
        )

        # 檢查是否有查詢條件
        if query and query.strip():
            # 有查詢條件，執行搜尋（包含 jieba 分詞、BM25 等 CPU 密集操作）
            found, result = await asyncio.to_thread(search_course_data_by_query, query, has_permission)
            if found:
                # 找到匹配結果，返回搜尋結果 + 權限提示
                return result + get_permission_notice(has_permission)
            else:
                # 找不到匹配結果，優先回傳近期課程而非全部
                if result.startswith("搜尋課程資料時發生錯誤"):
                    return result
                upcoming = await asyncio.to_thread(_get_upcoming_courses, has_permission, 2)
                if upcoming:
                    return f"未找到匹配 '{query}' 的課程資料，以下是近期課程：\n\n{upcoming}" + get_permission_notice(has_permission)
                else:
                    all_data = await asyncio.to_thread(get_all_course_data, has_permission)
                    return f"未找到匹配 '{query}' 的課程資料，以下是所有可用的課程資料：\n\n{all_data}" + get_permission_notice(has_permission)
        else:
            # 沒有查詢條件，返回所有課程資料 + 權限提示
            all_data = await asyncio.to_thread(get_all_course_data, has_permission)
            return all_data + get_permission_notice(has_permission)

    except Exception as e:
        return f"課程資料檢索錯誤: {str(e)}"


@mcp.tool(name="qa_retreviler")
async def search_qa_chunks_by_semantics(query: str, top_k: int = 5) -> str:
    """
    根據使用者的問題意圖，檢索與社團行政事務（如社費、參加資格、活動報名等）相關的 Q&A 條目，才呼叫此工具。
    Args:
        query: 使用者問題
        top_k: 返回最相關的結果數量（預設為5）
    """
    try:
        if not vector_store or not bm25_system:
            return "錯誤：RAG 系統未初始化，請檢查資料檔案是否存在"

        # 執行混合搜尋（FAISS + BM25，CPU 密集操作）
        results = await asyncio.to_thread(hybrid_search, query, top_k, 0.6)

        if not results:
            return "未找到相關資料"

        # 格式化結果
        formatted_results = []
        for i, (doc, score, methods) in enumerate(results, 1):
            content = doc.page_content
            metadata = doc.metadata

            result = f"=== 結果 {i} (相關度: {score:.3f}, 搜尋方法: {methods}) ===\n"
            result += f"內容：{content}\n"
            result += f"來源：{metadata.get('source', 'unknown')}\n"

            if metadata.get("type") == "faq":
                result += f"類型：FAQ\n"
                if metadata.get("tags"):
                    result += f"標籤：{', '.join(metadata.get('tags', []))}\n"
            elif metadata.get("type") == "entity":
                result += f"類型：實體資料 ({metadata.get('entity_type', 'unknown')})\n"
            elif metadata.get("type") == "paragraph":
                result += f"類型：段落\n"
                result += f"路徑：{metadata.get('path', 'unknown')}\n"
            elif metadata.get("section_title"):
                result += f"類型：文檔章節\n"
                result += f"章節：{metadata.get('section_title')}\n"

            formatted_results.append(result)

        return "\n\n".join(formatted_results)

    except Exception as e:
        return f"搜尋過程發生錯誤: {str(e)}"


# ---------------------------------------------------------------------------
# Staff notification via Discord
# ---------------------------------------------------------------------------
STAFF_NOTIFICATION_CHANNEL_ID = os.environ.get("STAFF_NOTIFICATION_CHANNEL_ID", "861698653231382568")
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")

def _send_discord_message(channel_id: str, message: str) -> bool:
    """Send a message to the specified Discord channel via HTTP API."""
    try:
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {
            "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
            "Content-Type": "application/json"
        }
        
        # Discord 訊息上限 2000 字元
        if len(message) > 1900:
            message = message[:1900] + "...(truncated)"
        
        payload = {"content": message}
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            eprint(f"[notify_staff] 成功發送通知到 Discord channel {channel_id}")
            return True
        else:
            eprint(f"[notify_staff] 發送失敗: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        eprint(f"[notify_staff] 發送通知時發生錯誤: {e}")
        return False


@mcp.tool(name="notify_staff")
async def notify_staff(message: str, user_name: str = "", platform: Optional[str] = "", context: str = "") -> str:
    """
    當 agent 認為需要通知幹部時，使用此工具發送通知訊息到幹部 Discord 頻道。
    
    適用情況：
    - 使用者詢問合作或商業相關事宜
    - 使用者有投訴或反映問題
    - 使用者詢問的問題超出 AI 能力範圍，需要人工處理
    - 任何需要幹部關注或處理的情況
    
    Args:
        message: 要通知幹部的訊息內容（應包含摘要和重要資訊）
        user_name: 發起詢問的使用者名稱（選填）
        platform: 使用者所在的平台（如 Discord、FB、LINE）（選填）
        context: 對話的相關上下文（選填）
    """
    try:
        # 格式化通知訊息
        from datetime import datetime, timezone, timedelta
        tz_taipei = timezone(timedelta(hours=8))
        timestamp = datetime.now(tz_taipei).strftime("%Y-%m-%d %H:%M:%S")
        
        notification = f"📢 **幹部通知** `{timestamp}`\n"
        
        if user_name:
            notification += f"👤 使用者：`{user_name}`"
            if platform:
                notification += f" ({platform})"
            notification += "\n"
        
        notification += f"📝 **通知內容**：\n{message}\n"
        
        if context:
            # 限制 context 長度
            context_preview = context[:500] + "..." if len(context) > 500 else context
            notification += f"\n💬 **相關上下文**：\n{context_preview}"
        
        success = await asyncio.to_thread(_send_discord_message, STAFF_NOTIFICATION_CHANNEL_ID, notification)

        if success:
            return "✅ 已成功通知幹部，他們會盡快處理您的需求。"
        else:
            return "⚠️ 通知發送失敗，請稍後再試或透過其他管道聯繫幹部。"
            
    except Exception as e:
        eprint(f"[notify_staff] 工具執行錯誤: {e}")
        return f"⚠️ 通知發送時發生錯誤：{str(e)}"


@mcp.tool(name="generate_checkin_code")
async def generate_checkin_code(platform: str, account_id: str, name: str = "", email: str = "") -> str:
    """
    產生使用者專屬的活動簽到碼連結。

    若使用者已是社員（系統可透過平台帳號 ID 在資料庫中找到），會自動使用資料庫中的姓名與 Email 產生簽到碼。
    若使用者不是社員或資料庫中查無資料，則需要使用者提供 name 和 email 來產生簽到碼，
    並提醒他們：擁有簽到碼不代表成功報名或有資格入場，請確認是否已成功報名活動（例如檢查 Email 是否收到報名成功信件）。

    Args:
        platform: 使用者所在的平台（Discord、FB、LINE），從系統訊息中取得 Platform
        account_id: 使用者在該平台上的唯一帳號 ID，從系統訊息中取得 Account ID
        name: （非社員時必填）使用者提供的姓名
        email: （非社員時必填）使用者提供的 Email
    """
    try:
        from urllib.parse import quote

        # 嘗試從資料庫查詢社員資料
        member = lookup_member_by_platform(platform, account_id)

        if member:
            member_name = member.get("name", "")
            member_email = member.get("email", "")
            if member_name and member_email:
                url = f"https://watsonshih.github.io/QuickRecord/user.html?name={quote(member_name)}&id={quote(member_email)}"
                return f"已為社員「{member_name}」產生專屬簽到碼連結：\n{url}"

        # 非社員或資料庫查無資料：需要使用者提供 name 和 email
        if not name or not email:
            return (
                "在資料庫中查無您的社員資料，請提供您的「姓名」和「Email」以產生簽到碼。"
            )

        if "@" not in email:
            return "請提供有效的 Email 地址（例如：yourname@gmail.com）"

        url = f"https://watsonshih.github.io/QuickRecord/user.html?name={quote(name)}&id={quote(email)}"
        return (
            f"已為「{name}」產生簽到碼連結：\n{url}\n\n"
            "提醒您：擁有簽到碼不代表已成功報名或有資格入場，"
            "請確認您是否已成功報名該活動（例如檢查 Email 是否有收到報名成功的確認信件）。"
        )

    except Exception as e:
        eprint(f"[generate_checkin_code] 工具執行錯誤: {e}")
        return f"⚠️ 產生簽到碼時發生錯誤：{str(e)}"


@mcp.tool(name="bind_email")
async def bind_email(email: str, platform: str, account_id: str) -> str:
    """
    透過 Email 綁定社員身分。使用者提供 Email 後，系統會比對社員資料庫，
    若找到匹配的社員，就將該平台的帳號 ID 綁定到該社員帳號上。
    綁定成功後，使用者在該平台上就會被識別為社員。

    注意：
    - Email 的 @ 前面部分不區分大小寫
    - 如果使用者提供的 Email 找不到對應社員，可能是當初申請時使用了其他 Email，請建議使用者聯繫幹部協助查詢

    Args:
        email: 使用者提供的 Email 地址（通常是 Gmail）
        platform: 使用者所在的平台（Discord、FB、LINE）
        account_id: 使用者在該平台上的唯一帳號 ID（從系統訊息中取得 Account ID）
    """
    try:
        if not email or "@" not in email:
            return "請提供有效的 Email 地址（例如：yourname@gmail.com）"

        result = _bind_email_to_platform(email, platform, account_id)
        return result["message"]
    except Exception as e:
        eprint(f"[bind_email] 工具執行錯誤: {e}")
        return f"⚠️ 綁定時發生錯誤：{str(e)}"


@mcp.tool(name="update_subscribe")
async def update_subscribe(platform: str, account_id: str, subscribe: str) -> str:
    """
    更新社員的課程通知訂閱設定。社員可以選擇在哪些平台接收每日課程提醒通知。
    系統每天 19:00 會自動通知隔日課程給訂閱者。

    注意：
    - 目前僅支援 discord 平台
    - 使用者必須已綁定該平台帳號才能訂閱該平台的通知
    - 傳入空字串表示取消所有訂閱

    Args:
        platform: 使用者所在的平台（Discord、FB、LINE），從系統訊息中取得 Platform
        account_id: 使用者在該平台上的唯一帳號 ID，從系統訊息中取得 Account ID
        subscribe: 訂閱的平台，目前僅接受 "discord" 或空字串（空字串表示取消所有訂閱）
    """
    try:
        result = _update_subscribe(platform, account_id, subscribe)
        return result["message"]
    except Exception as e:
        eprint(f"[update_subscribe] 工具執行錯誤: {e}")
        return f"⚠️ 更新訂閱設定時發生錯誤：{str(e)}"


@mcp.tool(name="update_personal_prompt")
async def update_personal_prompt(platform: str, account_id: str, personal_prompt: str) -> str:
    """
    記錄使用者的溝通風格、興趣領域或互動偏好。這些資訊會在未來的對話中幫助 Agent 調整回應方式。

    注意：
    - 最長 100 字，超過會自動截斷
    - 應整合既有記錄，而非單純覆蓋
    - 不需要每次對話都更新，有新的觀察才更新
    - 只記錄個性與偏好（如溝通風格、興趣領域），不記錄操作事件（如綁定、訂閱）或系統已有的資訊（如姓名、角色）

    Args:
        platform: 使用者所在的平台（Discord、FB、LINE），從系統訊息中取得 Platform
        account_id: 使用者在該平台上的唯一帳號 ID，從系統訊息中取得 Account ID
        personal_prompt: 使用者溝通風格、興趣與偏好的簡短描述（最多 100 字）
    """
    try:
        result = _update_personal_prompt(platform, account_id, personal_prompt)
        return result["message"]
    except Exception as e:
        eprint(f"[update_personal_prompt] 工具執行錯誤: {e}")
        return f"⚠️ 更新個性備註時發生錯誤：{str(e)}"


# ---------------------------------------------------------------------------
# Staff notification tool — notify all bound members about an event
# ---------------------------------------------------------------------------
STAFF_ROLE_KEYWORDS = ("社長", "部長", "部員")


def _is_staff_role(role: str) -> bool:
    """Check if the role contains any staff keyword (hard logic)."""
    if not role:
        return False
    return any(kw in role for kw in STAFF_ROLE_KEYWORDS)


def _get_upcoming_events(limit: int = 3) -> list[dict]:
    """Return the next N upcoming events from course data."""
    from datetime import datetime, timezone, timedelta
    tz_tpe = timezone(timedelta(hours=8))
    today = datetime.now(tz_tpe).strftime("%Y/%m/%d")

    global course_data
    load_course_data_from_url(course_data_url)
    if course_data is None or course_data.empty:
        return []

    upcoming = []
    for _, row in course_data.iterrows():
        event_date = str(row.get("時間", "")).strip()
        if not event_date or event_date < today:
            continue
        title = str(row.get("社課主題 / 活動名稱", "")).strip()
        if not title or title.lower() == "nan":
            continue
        weekday = str(row.get("星期", "")).strip() if pd.notna(row.get("星期")) else ""
        event_time = str(row.get("活動時間", "")).strip() if pd.notna(row.get("活動時間")) else ""
        venue = str(row.get("場地", "")).strip() if pd.notna(row.get("場地")) else ""
        upcoming.append({
            "date": event_date,
            "weekday": weekday,
            "time": event_time,
            "venue": venue,
            "title": title,
        })

    upcoming.sort(key=lambda e: e["date"])
    return upcoming[:limit]


def _find_event_by_date(target_date: str) -> dict | None:
    """Find a single event by exact date (YYYY/MM/DD)."""
    global course_data
    load_course_data_from_url(course_data_url)
    if course_data is None or course_data.empty:
        return None

    for _, row in course_data.iterrows():
        event_date = str(row.get("時間", "")).strip()
        if event_date == target_date:
            def _c(val):
                s = str(val).strip() if pd.notna(val) else ""
                return "" if s.lower() in ("nan", "-", "無") else s
            return {
                "date": event_date,
                "weekday": _c(row.get("星期")),
                "time": _c(row.get("活動時間")),
                "venue": _c(row.get("場地")),
                "title": _c(row.get("社課主題 / 活動名稱")),
                "speaker": _c(row.get("講者")),
                "outline": _c(row.get("課程大綱")),
                "target": _c(row.get("課程對象")),
                "livestream": _c(row.get("是否直播")),
                "recording": _c(row.get("是否錄影")),
                "online_link": _c(row.get("線上連結")),
                "slides": _c(row.get("課程講義")),
            }
    return None


def _format_staff_notification(event: dict, note: str = "") -> str:
    """Format the notification message for members (triggered by staff)."""
    lines = [f"NTUAI 活動通知"]
    lines.append("")
    lines.append(f"=== {event['title']} ===")
    lines.append(f"日期: {event['date']} {event['weekday']}")
    if event.get("time"):
        lines.append(f"時間: {event['time']}")
    if event.get("venue"):
        lines.append(f"地點: {event['venue']}")
    if event.get("speaker"):
        lines.append(f"講者: {event['speaker']}")
    if event.get("target"):
        lines.append(f"對象: {event['target']}")

    flags = []
    if event.get("livestream") == "Y":
        flags.append("線上直播")
    if event.get("recording") == "Y":
        flags.append("提供錄影")
    if flags:
        lines.append(f"備註: {' / '.join(flags)}")

    if event.get("outline"):
        outline = event["outline"]
        if len(outline) > 300:
            outline = outline[:300] + "..."
        lines.append(f"\n課程大綱:\n{outline}")

    if event.get("online_link"):
        lines.append(f"\n線上連結: {event['online_link']}")
    if event.get("slides"):
        lines.append(f"講義: {event['slides']}")

    if note:
        lines.append(f"\n--- 附註 ---\n{note}")

    return "\n".join(lines)


def _send_notification_to_members(message: str) -> dict:
    """Send a notification message to all valid bound members via Discord.

    Returns a summary dict with counts.
    """
    from daily_event_reminder import (
        load_members, get_valid_bound_members,
        send_discord_dm,
    )

    members = load_members()
    bound = get_valid_bound_members(members)

    discord_ok, discord_fail = 0, 0

    for m in bound:
        if m["discord_id"]:
            if send_discord_dm(m["discord_id"], message):
                discord_ok += 1
            else:
                discord_fail += 1
            time.sleep(0.5)

    return {
        "total_members": len(bound),
        "discord_ok": discord_ok,
        "discord_fail": discord_fail,
    }


@mcp.tool(name="notify_members")
async def notify_members(role: str, event_date: str = "", note: str = "", custom_message: str = "") -> str:
    """
    幹部專用工具：發送通知給所有已綁定帳號的有效社員（透過 Discord DM）。

    權限限制：僅限角色包含「社長」、「部長」、「部員」等幹部身分的使用者使用。
    系統會以硬邏輯檢查角色字串，非幹部無法使用此功能。

    支援兩種通知模式：
    A. 活動通知：提供 event_date，系統自動帶入完整活動資訊
    B. 自訂通知：提供 custom_message，直接發送自訂訊息（不需要選活動）

    使用流程：
    1. 若 event_date 和 custom_message 都未提供，工具會回傳即將舉辦的 3 場活動資訊供選擇
    2. 幹部可選擇一場活動（提供 event_date），或直接提供 custom_message 發送自訂通知
    3. note 為選填備註，活動通知模式下會附加在訊息最後

    Args:
        role: 使用者的角色（系統自動帶入，用於權限檢查）
        event_date: 要通知的活動日期（格式：YYYY/MM/DD），留空則列出即將舉辦的活動
        note: 幹部附註訊息（選填），活動通知時附加在訊息最後
        custom_message: 自訂通知訊息（選填），若提供則直接發送此訊息，不需選擇活動
    """
    # Hard check: must be staff
    if not _is_staff_role(role):
        return "此功能僅限幹部使用（角色需包含社長、部長或部員）。如果您是幹部但尚未綁定帳號，請先透過 Email 綁定身分。"

    # Mode A: custom message (no event needed)
    if custom_message and custom_message.strip():
        message = f"NTUAI 通知\n\n{custom_message.strip()}"
        eprint(f"[notify_members] Sending custom notification")

        result = await asyncio.to_thread(_send_notification_to_members, message)

        summary = (
            f"自訂通知已發送完成！\n\n"
            f"通知對象: {result['total_members']} 位已綁定帳號的有效社員\n"
            f"Discord: {result['discord_ok']} 成功, {result['discord_fail']} 失敗"
        )

        await asyncio.to_thread(
            _send_discord_message,
            os.environ.get("DISCORD_LOG_CHANNEL_ID", "1452311123574390886"),
            f"```\n[STAFF NOTIFY] Custom message\n"
            f"Discord: {result['discord_ok']}/{result['discord_ok']+result['discord_fail']}\n```"
        )
        return summary

    # Mode B: event notification
    if event_date and event_date.strip():
        event_date = event_date.strip()
        event = _find_event_by_date(event_date)
        if not event:
            return f"找不到日期為 {event_date} 的活動，請確認日期格式為 YYYY/MM/DD。"

        message = _format_staff_notification(event, note=note.strip() if note else "")
        eprint(f"[notify_members] Sending notification for {event['title']} ({event_date})")

        result = await asyncio.to_thread(_send_notification_to_members, message)

        summary = (
            f"通知已發送完成！\n\n"
            f"活動: {event['title']} ({event_date})\n"
            f"通知對象: {result['total_members']} 位已綁定帳號的有效社員\n"
            f"Discord: {result['discord_ok']} 成功, {result['discord_fail']} 失敗"
        )

        await asyncio.to_thread(
            _send_discord_message,
            os.environ.get("DISCORD_LOG_CHANNEL_ID", "1452311123574390886"),
            f"```\n[STAFF NOTIFY] {event['title']} ({event_date})\n"
            f"Discord: {result['discord_ok']}/{result['discord_ok']+result['discord_fail']}\n```"
        )
        return summary

    # Mode C: no event_date and no custom_message — list upcoming events
    upcoming = _get_upcoming_events(3)
    if not upcoming:
        return "目前沒有即將舉辦的活動。你也可以直接提供自訂訊息來通知社員。"

    lines = ["以下是即將舉辦的活動，請選擇要通知社員的活動：\n"]
    for i, ev in enumerate(upcoming, 1):
        parts = [f"{i}. {ev['title']}"]
        parts.append(f"   日期: {ev['date']} {ev['weekday']}")
        if ev["time"]:
            parts.append(f"   時間: {ev['time']}")
        if ev["venue"]:
            parts.append(f"   地點: {ev['venue']}")
        lines.append("\n".join(parts))

    lines.append("\n請告訴我要通知哪一場活動（提供日期即可），也可以直接提供自訂訊息來通知社員。")
    return "\n\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MCP Server for NTUAI RAG")
    parser.add_argument("--http", action="store_true", help="Run in HTTP (SSE) mode instead of stdio")
    parser.add_argument("--port", type=int, default=5191, help="Port for HTTP server (default: 5191)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host for HTTP server (default: 0.0.0.0)")
    args = parser.parse_args()
    
    if args.http:
        # Use FastMCP's built-in streamable-http transport (stateless mode)
        # This avoids the SSE session leak in mcp/server/sse.py where
        # _read_stream_writers entries accumulate and never get cleaned up.
        import uvicorn
        from starlette.routing import Route
        from starlette.responses import JSONResponse

        async def health_check(request):
            """Health check endpoint"""
            return JSONResponse({"status": "ok"})

        mcp._custom_starlette_routes = [
            Route("/health", health_check, methods=["GET"]),
        ]

        eprint(f"Starting MCP server (streamable-http) on {args.host}:{args.port}...")
        eprint(f"MCP endpoint: http://{args.host}:{args.port}/mcp")
        eprint(f"Health check: http://{args.host}:{args.port}/health")

        starlette_app = mcp.streamable_http_app()
        uvicorn.run(starlette_app, host=args.host, port=args.port, log_level="info")
    else:
        eprint("Starting MCP server in stdio mode...")
        mcp.run(transport="stdio")
