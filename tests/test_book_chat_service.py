"""Tests for book_chat indexing and query service (no live LLM)."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from book_chat.embeddings import FakeHashEmbedder
from book_chat.index_store import index_path_for_book, read_passages
from book_chat.service import (
    DEFAULT_ANSWER_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    BookChatNotFoundError,
    get_index_status,
    index_passages,
    query_passages,
)


@pytest.fixture
def workspace() -> Path:
    with TemporaryDirectory() as td:
        yield Path(td).resolve()


def test_index_passages_writes_jsonl_with_embeddings(workspace: Path) -> None:
    embedder = FakeHashEmbedder(dimension=16)
    result = index_passages(
        workspace,
        "book-1",
        [
            {"chapter": "Intro", "text": "Start with small habits."},
            {"chapter": "Ch2", "text": "Rest is part of growth."},
        ],
        embedder=embedder,
    )
    assert result["ok"] is True
    assert result["book_id"] == "book-1"
    assert result["passage_count"] == 2
    assert result["embedding_model"] == embedder.model_name

    path = index_path_for_book(workspace, "book-1")
    stored = read_passages(path)
    assert len(stored) == 2
    assert all("embedding" in p and len(p["embedding"]) == 16 for p in stored)
    assert stored[0]["chapter"] == "Intro"


def test_query_passages_retrieval_only_answer_and_citations(workspace: Path) -> None:
    embedder = FakeHashEmbedder(dimension=16)
    index_passages(
        workspace,
        "book-1",
        [
            {"chapter": "Intro", "text": "Discipline grows through repeated small choices."},
            {"chapter": "Ch2", "text": "Sleep and rest restore the mind."},
        ],
        embedder=embedder,
    )
    out = query_passages(
        workspace,
        "book-1",
        "How does discipline develop?",
        top_k=2,
        embedder=embedder,
        use_model=False,
    )
    assert out["book_id"] == "book-1"
    assert out["fallback_used"] is False
    assert out["model_provider"] == "retrieval_only"
    assert out["model"] == DEFAULT_ANSWER_MODEL
    assert len(out["retrieved_passages"]) >= 1
    assert len(out["citations"]) >= 1
    assert "discipline" in out["answer"].lower() or "Discipline" in out["answer"]
    cite = out["citations"][0]
    assert "passage_id" in cite
    assert "chapter" in cite
    assert "snippet" in cite


def test_query_passages_missing_index_raises(workspace: Path) -> None:
    embedder = FakeHashEmbedder(dimension=8)
    with pytest.raises(BookChatNotFoundError) as exc:
        query_passages(workspace, "missing-book", "hello?", embedder=embedder)
    assert "missing-book" in str(exc.value)


def test_get_index_status_unindexed(workspace: Path) -> None:
    status = get_index_status(workspace, "book-1")
    assert status["ok"] is True
    assert status["book_id"] == "book-1"
    assert status["indexed"] is False
    assert status["passage_count"] == 0


def test_get_index_status_indexed(workspace: Path) -> None:
    embedder = FakeHashEmbedder(dimension=8)
    index_passages(
        workspace,
        "book-1",
        [{"chapter": "Intro", "text": "Indexed passage text."}],
        embedder=embedder,
    )
    status = get_index_status(workspace, "book-1")
    assert status["indexed"] is True
    assert status["passage_count"] == 1
    assert status["embedding_model"] == embedder.model_name
    assert "library/book_chat/book-1/passages.jsonl" in status["index_path"]


def test_index_passages_replaces_existing_index(workspace: Path) -> None:
    embedder = FakeHashEmbedder(dimension=8)
    index_passages(workspace, "book-1", [{"chapter": "A", "text": "one"}], embedder=embedder)
    index_passages(workspace, "book-1", [{"chapter": "B", "text": "two only"}], embedder=embedder)
    stored = read_passages(index_path_for_book(workspace, "book-1"))
    assert len(stored) == 1
    assert stored[0]["text"] == "two only"


def test_index_passages_emits_progress_callback(workspace: Path) -> None:
    embedder = FakeHashEmbedder(dimension=8)
    events: list[dict] = []

    def on_progress(data: dict) -> None:
        events.append(dict(data))

    index_passages(
        workspace,
        "book-1",
        [
            {"chapter": "Intro", "text": "First passage."},
            {"chapter": "Ch2", "text": "Second passage."},
            {"chapter": "Ch3", "text": "Third passage."},
        ],
        embedder=embedder,
        progress_callback=on_progress,
    )
    stages = [e.get("stage") for e in events]
    assert "embedding" in stages
    assert "saving" in stages
    assert "complete" in stages

    embed_events = [e for e in events if e.get("stage") == "embedding"]
    assert embed_events
    assert embed_events[-1]["current"] == embed_events[-1]["total"] == 3
    assert embed_events[-1]["percent"] == 100

    complete_events = [e for e in events if e.get("stage") == "complete"]
    assert complete_events
    assert complete_events[-1]["percent"] == 100
