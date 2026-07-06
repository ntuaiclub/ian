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

import hashlib
import json
import math
import os
import re
from collections import Counter
from functools import lru_cache
from typing import Any, Dict, List, Tuple

import jieba
import jieba.analyse
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ian.config import CACHE_DIR, DATA_DIR
from ian.utils.console import eprint


vector_store = None
embedding_model = None
documents = []
bm25_system = None
bm25_corpus = []
bm25_docs = []

FAISS_INDEX_DIR = str(CACHE_DIR / "faiss_index")
FAISS_HASH_FILE = str(CACHE_DIR / "faiss_source_hash.txt")


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
            self.idf[word] = math.log(1 + (self.doc_count - freq + 0.5) / (freq + 0.5))

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


@lru_cache(maxsize=10)
def load_jsonl_data(file_path: str) -> List[Dict[str, Any]]:
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
    try:
        return jieba.analyse.extract_tags(text, topK=top_k, withWeight=False)
    except Exception:
        words = re.findall(r"[\u4e00-\u9fff]+", text)
        word_freq = Counter(words)
        return [word for word, _ in word_freq.most_common(top_k) if len(word) > 1]


def create_enhanced_documents(jsonl_data: List[Dict], md_content: str) -> List[Document]:
    enhanced_documents = []

    for item in jsonl_data:
        if item.get("type") == "faq":
            question = item.get("question", "").strip()
            answer = item.get("answer", "").strip()
            if question and answer:
                content = f"問題：{question}\n答案：{answer}"
                keywords = extract_keywords(question + " " + answer)
                if keywords:
                    content += f"\n關鍵字：{', '.join(keywords)}"
                enhanced_documents.append(
                    Document(
                        page_content=content,
                        metadata={
                            "source": "faq",
                            "id": item.get("id", ""),
                            "type": "faq",
                            "question": question,
                            "answer": answer,
                            "tags": item.get("tags", []),
                            "keywords": keywords,
                        },
                    )
                )

        elif item.get("type") == "paragraph":
            content = item.get("text", "").strip()
            if content:
                path = item.get("path", "未分類")
                enhanced_content = f"分類：{path}\n內容：{content}"
                keywords = extract_keywords(content)
                if keywords:
                    enhanced_content += f"\n關鍵字：{', '.join(keywords)}"
                enhanced_documents.append(
                    Document(
                        page_content=enhanced_content,
                        metadata={
                            "source": "paragraph",
                            "id": item.get("id", ""),
                            "path": path,
                            "type": "paragraph",
                            "keywords": keywords,
                        },
                    )
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
            enhanced_documents.append(
                Document(
                    page_content=content,
                    metadata={
                        "source": "entity",
                        "id": item.get("id", ""),
                        "type": "entity",
                        "entity_type": entity_type,
                        "keywords": keywords,
                    },
                )
            )

    if md_content:
        sections = re.split(r"\n(?=#{1,3}\s)", md_content)
        for i, section in enumerate(sections):
            if not section.strip():
                continue
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
                        enhanced_documents.append(
                            Document(
                                page_content=content,
                                metadata={
                                    "source": "markdown",
                                    "section_title": title,
                                    "chunk_id": f"{i}_{j}",
                                    "type": "markdown_chunk",
                                    "keywords": keywords,
                                },
                            )
                        )
            else:
                keywords = extract_keywords(section)
                content = f"章節：{title}\n內容：{section.strip()}"
                if keywords:
                    content += f"\n關鍵字：{', '.join(keywords)}"
                enhanced_documents.append(
                    Document(
                        page_content=content,
                        metadata={
                            "source": "markdown",
                            "section_title": title,
                            "chunk_id": str(i),
                            "type": "markdown_section",
                            "keywords": keywords,
                        },
                    )
                )

    return enhanced_documents


def build_bm25_index():
    global bm25_system, bm25_corpus, bm25_docs, documents
    bm25_docs = []
    bm25_corpus = []
    for doc in documents:
        tokens = list(jieba.cut(doc.page_content))
        tokens = [token.strip() for token in tokens if token.strip() and len(token.strip()) > 1]
        bm25_corpus.append(tokens)
        bm25_docs.append(doc)

    bm25_system = SimpleBM25(bm25_corpus)
    eprint(f"BM25 索引建立完成: {len(bm25_corpus)} 個文檔")


def bm25_search(query: str, top_k: int = 10) -> List[Tuple[Document, float]]:
    if not bm25_system:
        return []

    query_tokens = list(jieba.cut(query))
    query_tokens = [token.strip() for token in query_tokens if token.strip() and len(token.strip()) > 1]
    if not query_tokens:
        return []

    scores = bm25_system.get_scores(query_tokens)
    doc_scores = [(bm25_docs[i], scores[i]) for i in range(len(scores))]
    doc_scores.sort(key=lambda x: x[1], reverse=True)
    return doc_scores[:top_k]


def semantic_search(query: str, top_k: int = 10) -> List[Tuple[Document, float]]:
    if not vector_store:
        return []
    return vector_store.similarity_search_with_score(query, k=top_k)


def hybrid_search(query: str, top_k: int = 5, alpha: float = 0.6) -> List[Tuple[Document, float, str]]:
    bm25_results = bm25_search(query, top_k * 2)
    semantic_results = semantic_search(query, top_k * 2)

    def normalize_scores(results):
        if not results:
            return []
        scores = [score for _, score in results]
        min_score, max_score = min(scores), max(scores)
        if max_score == min_score:
            return [(doc, 0.5) for doc, _ in results]
        return [(doc, (score - min_score) / (max_score - min_score)) for doc, score in results]

    norm_bm25 = normalize_scores(bm25_results)
    norm_semantic = [(doc, 1 - score) for doc, score in normalize_scores(semantic_results)]
    doc_scores = {}

    for doc, score in norm_bm25:
        doc_id = doc.metadata.get("id", str(hash(doc.page_content)))
        doc_scores[doc_id] = {
            "doc": doc,
            "bm25_score": score,
            "semantic_score": 0,
            "methods": ["BM25"],
        }

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

    final_results = []
    for info in doc_scores.values():
        hybrid_score = alpha * info["bm25_score"] + (1 - alpha) * info["semantic_score"]
        methods_str = "+".join(info["methods"])
        final_results.append((info["doc"], hybrid_score, methods_str))

    final_results.sort(key=lambda x: x[1], reverse=True)
    return final_results[:top_k]


def _compute_source_hash(jsonl_path: str, md_path: str) -> str:
    hasher = hashlib.md5()
    try:
        with open(jsonl_path, "rb") as f:
            hasher.update(f.read())
    except FileNotFoundError:
        pass
    try:
        with open(md_path, "rb") as f:
            hasher.update(f.read())
    except FileNotFoundError:
        pass
    return hasher.hexdigest()


def _get_saved_hash() -> str:
    try:
        if os.path.exists(FAISS_HASH_FILE):
            with open(FAISS_HASH_FILE, "r") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


def _save_hash(hash_value: str):
    os.makedirs(str(CACHE_DIR), exist_ok=True)
    with open(FAISS_HASH_FILE, "w") as f:
        f.write(hash_value)


def _try_load_faiss_index():
    global vector_store, embedding_model
    if not os.path.exists(FAISS_INDEX_DIR):
        return False
    try:
        vector_store = FAISS.load_local(
            FAISS_INDEX_DIR,
            embedding_model,
            allow_dangerous_deserialization=True,
        )
        eprint("[快取] 從本地快取載入 FAISS 索引")
        return True
    except Exception as e:
        eprint(f"[快取] 載入 FAISS 索引失敗: {e}")
        return False


def _save_faiss_index():
    try:
        os.makedirs(FAISS_INDEX_DIR, exist_ok=True)
        vector_store.save_local(FAISS_INDEX_DIR)
        eprint("[快取] FAISS 索引已儲存到本地快取")
    except Exception as e:
        eprint(f"[快取] 儲存 FAISS 索引失敗: {e}")


def _try_move_faiss_to_gpu():
    global vector_store
    try:
        import faiss as faiss_lib

        if faiss_lib.get_num_gpus() > 0:
            gpu_res = faiss_lib.StandardGpuResources()
            cpu_index = vector_store.index
            gpu_index = faiss_lib.index_cpu_to_gpu(gpu_res, 0, cpu_index)
            vector_store.index = gpu_index
            eprint(f"[GPU] FAISS 索引已載入 GPU (共 {faiss_lib.get_num_gpus()} 個 GPU)")
            return True
        eprint("[GPU] 未偵測到可用的 GPU，使用 CPU 模式")
        return False
    except Exception as e:
        eprint(f"[GPU] 無法將 FAISS 索引移到 GPU: {e}")
        return False


def initialize_rag_system():
    global vector_store, embedding_model, documents

    jieba.initialize()
    try:
        embedding_model = HuggingFaceEmbeddings(
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        eprint("多語言嵌入模型初始化完成")
    except Exception as e:
        eprint(f"嵌入模型初始化失敗: {e}")
        return False

    jsonl_file_path = str(DATA_DIR / "ntuai_recompiled_index.jsonl")
    md_file_path = str(DATA_DIR / "ntuai_zh_base.md")

    try:
        current_hash = _compute_source_hash(jsonl_file_path, md_file_path)
        saved_hash = _get_saved_hash()
        use_cache = (current_hash == saved_hash) and os.path.exists(FAISS_INDEX_DIR)

        if use_cache:
            eprint(f"[快取] 來源檔案未變更 (hash: {current_hash[:8]}...)，嘗試載入快取")
            if _try_load_faiss_index():
                jsonl_data = load_jsonl_data(jsonl_file_path)
                md_content = load_markdown_data(md_file_path)
                documents = create_enhanced_documents(jsonl_data, md_content)
                build_bm25_index()
                _try_move_faiss_to_gpu()
                return True
            eprint("[快取] 快取載入失敗，重建索引")
        elif saved_hash:
            eprint(f"[快取] 來源檔案已變更 (舊: {saved_hash[:8]}... → 新: {current_hash[:8]}...)，重建索引")
        else:
            eprint(f"[快取] 首次建立索引 (hash: {current_hash[:8]}...)")

        jsonl_data = load_jsonl_data(jsonl_file_path)
        md_content = load_markdown_data(md_file_path)
        documents = create_enhanced_documents(jsonl_data, md_content)

        if documents:
            vector_store = FAISS.from_documents(documents, embedding_model)
            eprint(f"向量資料庫建立完成, 包含 {len(documents)} 個文檔")
            _save_faiss_index()
            _save_hash(current_hash)
            build_bm25_index()
            _try_move_faiss_to_gpu()
            return True

        eprint("沒有找到任何文檔資料")
        return False
    except Exception as e:
        eprint(f"初始化過程發生錯誤: {e}")
        return False


def is_initialized() -> bool:
    return bool(vector_store and bm25_system)
