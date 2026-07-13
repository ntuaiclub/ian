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

import pytest
from langchain_core.documents import Document

from ian.services import rag


@pytest.fixture(autouse=True)
def reset_rag_helper_state(monkeypatch):
    rag.load_jsonl_data.cache_clear()
    rag.load_markdown_data.cache_clear()
    monkeypatch.setattr(rag, "bm25_system", None)
    monkeypatch.setattr(rag, "bm25_corpus", [])
    monkeypatch.setattr(rag, "bm25_docs", [])
    yield
    getattr(rag.load_jsonl_data, "cache_clear", lambda: None)()
    getattr(rag.load_markdown_data, "cache_clear", lambda: None)()


def test_simple_bm25_scores_matching_document_higher():
    bm25 = rag.SimpleBM25([["ai", "course"], ["member", "fee"]])

    scores = bm25.get_scores(["ai"])

    assert scores[0] > scores[1]


def test_load_jsonl_data_reads_valid_nonempty_lines(tmp_path):
    source = tmp_path / "source.jsonl"
    source.write_text(
        '{"type": "faq", "id": "faq-1"}\n\n'
        '{"type": "paragraph", "id": "paragraph-1"}\n',
        encoding="utf-8",
    )

    assert rag.load_jsonl_data(str(source)) == [
        {"type": "faq", "id": "faq-1"},
        {"type": "paragraph", "id": "paragraph-1"},
    ]


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        pytest.param("missing.jsonl", None, id="missing-file"),
        pytest.param("malformed.jsonl", "not-json\n", id="malformed-content"),
    ],
)
def test_load_jsonl_data_returns_empty_for_unreadable_sources(
    tmp_path, filename, content
):
    source = tmp_path / filename
    if content is not None:
        source.write_text(content, encoding="utf-8")

    assert rag.load_jsonl_data(str(source)) == []


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        pytest.param("# NTUAI\n\nWelcome", "# NTUAI\n\nWelcome", id="valid-file"),
        pytest.param(None, "", id="missing-file"),
    ],
)
def test_load_markdown_data_handles_valid_and_missing_files(
    tmp_path, content, expected
):
    source = tmp_path / "source.md"
    if content is not None:
        source.write_text(content, encoding="utf-8")

    assert rag.load_markdown_data(str(source)) == expected


@pytest.mark.parametrize(
    ("item", "expected_type", "expected_parts"),
    [
        pytest.param(
            {
                "type": "faq",
                "id": "faq-1",
                "question": "How to join?",
                "answer": "Complete the form.",
                "tags": ["membership"],
            },
            "faq",
            ("問題：How to join?", "答案：Complete the form.", "關鍵字：keyword"),
            id="faq",
        ),
        pytest.param(
            {
                "type": "paragraph",
                "id": "paragraph-1",
                "path": "About / Mission",
                "text": "Learn and build together.",
            },
            "paragraph",
            ("分類：About / Mission", "內容：Learn and build together."),
            id="paragraph",
        ),
        pytest.param(
            {
                "type": "entity",
                "id": "entity-1",
                "entity_type": "contact",
                "name": "NTUAI",
                "emails": ["club@example.test"],
                "urls": ["https://example.test"],
            },
            "entity",
            ("實體類型：contact", "名稱：NTUAI", "club@example.test", "https://example.test"),
            id="entity",
        ),
    ],
)
def test_create_enhanced_documents_maps_jsonl_types(
    monkeypatch, item, expected_type, expected_parts
):
    monkeypatch.setattr(rag, "extract_keywords", lambda _text: ["keyword"])

    documents = rag.create_enhanced_documents([item], "")

    assert len(documents) == 1
    assert documents[0].metadata["type"] == expected_type
    assert documents[0].metadata["id"] == item["id"]
    assert all(part in documents[0].page_content for part in expected_parts)


def test_create_enhanced_documents_maps_markdown_sections(monkeypatch):
    monkeypatch.setattr(rag, "extract_keywords", lambda _text: ["keyword"])

    documents = rag.create_enhanced_documents([], "# Introduction\nWelcome\n## Events\nWeekly talks")

    assert [document.metadata["section_title"] for document in documents] == [
        "Introduction",
        "Events",
    ]
    assert all(document.metadata["type"] == "markdown_section" for document in documents)
    assert "內容：## Events\nWeekly talks" in documents[1].page_content


def _document(document_id: str, content: str) -> Document:
    return Document(page_content=content, metadata={"id": document_id})


def test_build_bm25_index_and_search_rank_matching_documents(monkeypatch):
    source_documents = [
        _document("course", "ai course workshop"),
        _document("membership", "member fee payment"),
        _document("community", "club community"),
    ]
    monkeypatch.setattr(rag, "documents", source_documents)
    monkeypatch.setattr(rag.jieba, "cut", lambda text: text.split())

    rag.build_bm25_index()
    results = rag.bm25_search("member fee", top_k=2)

    assert rag.bm25_docs == source_documents
    assert rag.bm25_corpus == [
        ["ai", "course", "workshop"],
        ["member", "fee", "payment"],
        ["club", "community"],
    ]
    assert results[0][0].metadata["id"] == "membership"
    assert results[0][1] > results[1][1]
    assert len(results) == 2


@pytest.mark.parametrize("query", ["", "a"])
def test_bm25_search_returns_empty_without_searchable_query(monkeypatch, query):
    monkeypatch.setattr(rag, "bm25_system", rag.SimpleBM25([["course"]]))
    monkeypatch.setattr(rag, "bm25_docs", [_document("course", "course")])
    monkeypatch.setattr(rag.jieba, "cut", lambda text: text.split())

    assert rag.bm25_search(query) == []


def test_hybrid_search_combines_and_ranks_bm25_and_semantic_results(monkeypatch):
    bm25_first = _document("bm25-first", "keyword match")
    semantic_first = _document("semantic-first", "meaning match")
    shared = _document("shared", "both match")

    monkeypatch.setattr(
        rag,
        "bm25_search",
        lambda query, top_k: [(bm25_first, 10.0), (shared, 5.0), (semantic_first, 0.0)],
    )
    monkeypatch.setattr(
        rag,
        "semantic_search",
        lambda query, top_k: [(semantic_first, 0.0), (shared, 0.5), (bm25_first, 1.0)],
    )

    results = rag.hybrid_search("query", top_k=2, alpha=0.25)

    assert [document.metadata["id"] for document, _score, _methods in results] == [
        "semantic-first",
        "shared",
    ]
    assert all(methods == "BM25+Semantic" for _document, _score, methods in results)
    assert results[0][1] > results[1][1]


@pytest.mark.parametrize(
    ("jsonl_content", "markdown_content"),
    [
        pytest.param(b"jsonl", b"markdown", id="both-files"),
        pytest.param(b"jsonl", None, id="missing-markdown"),
        pytest.param(None, b"markdown", id="missing-jsonl"),
        pytest.param(None, None, id="both-missing"),
    ],
)
def test_compute_source_hash_uses_existing_files_only(
    tmp_path, jsonl_content, markdown_content
):
    jsonl_path = tmp_path / "source.jsonl"
    markdown_path = tmp_path / "source.md"
    if jsonl_content is not None:
        jsonl_path.write_bytes(jsonl_content)
    if markdown_content is not None:
        markdown_path.write_bytes(markdown_content)

    result = rag._compute_source_hash(str(jsonl_path), str(markdown_path))

    expected_content = (jsonl_content or b"") + (markdown_content or b"")
    assert result == hashlib.md5(expected_content).hexdigest()


def _stub_rag_initialization(monkeypatch):
    monkeypatch.setattr(rag.jieba, "initialize", lambda: None)
    monkeypatch.setattr(rag, "HuggingFaceEmbeddings", lambda **_kwargs: object())
    monkeypatch.setattr(rag, "_compute_source_hash", lambda *_args: "source-hash")
    monkeypatch.setattr(rag, "_get_saved_hash", lambda: "source-hash")
    monkeypatch.setattr(rag.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(rag, "load_jsonl_data", lambda _path: [])
    monkeypatch.setattr(rag, "load_markdown_data", lambda _path: "")
    monkeypatch.setattr(
        rag,
        "create_enhanced_documents",
        lambda *_args: [_document("cached", "cached document")],
    )
    monkeypatch.setattr(rag, "build_bm25_index", lambda: None)
    monkeypatch.setattr(rag, "_try_move_faiss_to_gpu", lambda: False)


def test_initialize_rag_system_logs_cache_success(monkeypatch, capsys):
    _stub_rag_initialization(monkeypatch)
    monkeypatch.setattr(rag, "_try_load_faiss_index", lambda: True)

    assert rag.initialize_rag_system() is True

    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [entry["event"] for entry in entries] == ["job_started", "job_completed"]
    assert entries[-1]["source"] == "cache"
    assert entries[-1]["document_count"] == 1


def test_initialize_rag_system_logs_embedding_failure_without_error_message(
    monkeypatch, capsys
):
    monkeypatch.setattr(rag.jieba, "initialize", lambda: None)
    monkeypatch.setattr(
        rag,
        "HuggingFaceEmbeddings",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("private model detail")),
    )

    assert rag.initialize_rag_system() is False

    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert entries[-1]["event"] == "job_failed"
    assert entries[-1]["stage"] == "embedding_model"
    assert entries[-1]["error_type"] == "RuntimeError"
    assert "private model detail" not in json.dumps(entries)


def test_initialize_rag_system_logs_tokenizer_failure(monkeypatch, capsys):
    monkeypatch.setattr(
        rag.jieba,
        "initialize",
        lambda: (_ for _ in ()).throw(RuntimeError("private tokenizer detail")),
    )
    monkeypatch.setattr(
        rag,
        "HuggingFaceEmbeddings",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("embedding should not be initialized")
        ),
    )

    assert rag.initialize_rag_system() is False

    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert entries[-1]["event"] == "job_failed"
    assert entries[-1]["stage"] == "tokenizer"
    assert entries[-1]["error_type"] == "RuntimeError"
    assert "private tokenizer detail" not in json.dumps(entries)
