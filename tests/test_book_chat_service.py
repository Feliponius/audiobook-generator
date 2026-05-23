"""Tests for book_chat indexing and query service (no live LLM)."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from book_chat.embeddings import FakeHashEmbedder
from book_chat.index_store import index_path_for_book, read_passages
from book_chat.model_gateway import HermesGatewayResult
from book_chat.service import (
    DEFAULT_ANSWER_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    BookChatNotFoundError,
    build_book_chat_prompt,
    get_index_status,
    index_passages,
    normalize_answer_action,
    query_passages,
)


@pytest.fixture
def workspace() -> Path:
    with TemporaryDirectory() as td:
        yield Path(td).resolve()


def test_index_passages_preserves_source_href_and_chunk_metadata(workspace: Path) -> None:
    embedder = FakeHashEmbedder(dimension=16)
    index_passages(
        workspace,
        "book-1",
        [
            {
                "chapter": "Chapter 5",
                "text": "A useful passage about influence.",
                "source": "chapter_5.xhtml",
                "chapter_index": 5,
                "chunk_index": 3,
            }
        ],
        embedder=embedder,
    )
    stored = read_passages(index_path_for_book(workspace, "book-1"))
    assert len(stored) == 1
    row = stored[0]
    assert row["source"] == "chapter_5.xhtml"
    assert row["href"] == "chapter_5.xhtml"
    assert row["chapter_index"] == 5
    assert row["chunk_index"] == 3


def test_query_passages_citations_include_passage_metadata(workspace: Path) -> None:
    embedder = FakeHashEmbedder(dimension=16)
    index_passages(
        workspace,
        "book-1",
        [
            {
                "chapter": "Chapter 5",
                "text": "A useful passage about influence.",
                "source": "chapter_5.xhtml",
                "chapter_index": 5,
                "chunk_index": 3,
            },
            {"chapter": "Ch2", "text": "Unrelated rest and sleep topic."},
        ],
        embedder=embedder,
    )
    out = query_passages(
        workspace,
        "book-1",
        "influence in relationships",
        top_k=1,
        embedder=embedder,
        use_model=False,
    )
    cite = out["citations"][0]
    assert cite["source"] == "chapter_5.xhtml"
    assert cite["href"] == "chapter_5.xhtml"
    assert cite["chapter_index"] == 5
    assert cite["chunk_index"] == 3


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


def test_normalize_answer_action_defaults_unknown_to_answer() -> None:
    assert normalize_answer_action(None) == "answer"
    assert normalize_answer_action("") == "answer"
    assert normalize_answer_action("SOCRATIC") == "socratic"
    assert normalize_answer_action("explain") == "explain"
    assert normalize_answer_action("not-a-mode") == "answer"


def test_build_book_chat_prompt_socratic_includes_grounding_and_passage_ids() -> None:
    hits = [
        {
            "passage_id": "passage_book-1_0",
            "chapter": "Intro",
            "text": "Influence grows through trust and reciprocity.",
            "snippet": "Influence grows through trust",
        }
    ]
    prompt = build_book_chat_prompt("How do I build influence?", hits, action="socratic")
    assert "passage_book-1_0" in prompt
    assert "Socratic" in prompt or "socratic" in prompt
    assert "do not invent" in prompt.lower() or "not invent" in prompt.lower()
    assert "How do I build influence?" in prompt


def test_build_book_chat_prompt_practice_requires_citations() -> None:
    hits = [
        {
            "passage_id": "passage_book-1_1",
            "chapter": "Ch2",
            "text": "Practice small conversations daily.",
            "snippet": "Practice small conversations",
        }
    ]
    prompt = build_book_chat_prompt("How can I practice?", hits, action="practice")
    assert "practice" in prompt.lower()
    assert "passage_book-1_1" in prompt
    assert "citation" in prompt.lower() or "Sources" in prompt or "[passage_" in prompt


def test_query_passages_use_model_socratic_calls_gateway(workspace: Path, monkeypatch) -> None:
    embedder = FakeHashEmbedder(dimension=16)
    index_passages(
        workspace,
        "book-1",
        [{"chapter": "Intro", "text": "Ask questions before offering advice."}],
        embedder=embedder,
    )
    captured: dict = {}

    def fake_gateway(prompt: str, *, model: str = DEFAULT_ANSWER_MODEL, **kwargs):
        captured["prompt"] = prompt
        captured["model"] = model
        return HermesGatewayResult(
            ok=True,
            provider="hermes_openai_codex",
            model=model,
            text="1. What assumptions are you making?\n2. What would the book suggest?",
        )

    monkeypatch.setattr("book_chat.service.ask_via_hermes_codex", fake_gateway)
    out = query_passages(
        workspace,
        "book-1",
        "dealing with coworkers",
        embedder=embedder,
        use_model=True,
        action="socratic",
    )
    assert "Socratic" in captured["prompt"] or "socratic" in captured["prompt"]
    assert out["action"] == "socratic"
    assert out["fallback_used"] is False
    assert out["model_provider"] == "hermes_openai_codex"
    assert "?" in out["answer"]


def test_query_passages_challenge_falls_back_action_aware(workspace: Path, monkeypatch) -> None:
    embedder = FakeHashEmbedder(dimension=16)
    index_passages(
        workspace,
        "book-1",
        [{"chapter": "Intro", "text": "Assumptions about laziness may hide deeper blockers."}],
        embedder=embedder,
    )

    def failing_gateway(*args, **kwargs):
        return HermesGatewayResult(
            ok=False,
            provider="hermes_openai_codex",
            model=DEFAULT_ANSWER_MODEL,
            text="",
            error="timeout",
        )

    monkeypatch.setattr("book_chat.service.ask_via_hermes_codex", failing_gateway)
    out = query_passages(
        workspace,
        "book-1",
        "lazy coworkers",
        embedder=embedder,
        use_model=True,
        action="challenge",
    )
    assert out["action"] == "challenge"
    assert out["fallback_used"] is True
    assert out["model_provider"] == "retrieval_only"
    answer = out["answer"].lower()
    assert "fallback" in answer or "assumption" in answer
