"""Book Chat indexing and grounded query service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from book_chat.embeddings import DEFAULT_BGE_MODEL, LocalBGEEmbedder, TextEmbedder
from book_chat.index_store import index_path_for_book, read_passages, retrieve_top_k, write_passages
from book_chat.model_gateway import ask_via_hermes_codex

DEFAULT_EMBEDDING_MODEL = DEFAULT_BGE_MODEL
DEFAULT_ANSWER_MODEL = "gpt-5.5"
RETRIEVAL_ONLY_PROVIDER = "retrieval_only"


class BookChatNotFoundError(FileNotFoundError):
    """Raised when a book has no passage index on disk."""


def _default_embedder() -> TextEmbedder:
    return LocalBGEEmbedder()


def _passage_id(book_id: str, index: int) -> str:
    return f"passage_{book_id}_{index}"


def index_passages(
    root: Path,
    book_id: str,
    raw_passages: list[dict[str, Any]],
    *,
    embedder: TextEmbedder | None = None,
) -> dict[str, Any]:
    emb = embedder or _default_embedder()
    records: list[dict[str, Any]] = []
    for i, item in enumerate(raw_passages):
        chapter = str(item.get("chapter") or "").strip()
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        records.append(
            {
                "id": _passage_id(book_id, i),
                "book_id": book_id,
                "chapter": chapter,
                "text": text,
                "embedding_model": emb.model_name,
                "embedding": emb.embed(text),
            }
        )
    path = index_path_for_book(root, book_id)
    write_passages(path, records)
    return {
        "ok": True,
        "book_id": book_id,
        "status": "indexed",
        "passage_count": len(records),
        "embedding_model": emb.model_name,
    }


def _citation_from_hit(hit: dict[str, Any]) -> dict[str, Any]:
    return {
        "passage_id": hit.get("passage_id"),
        "chapter": hit.get("chapter") or "",
        "snippet": hit.get("snippet") or "",
    }


def _retrieval_only_answer(question: str, hits: list[dict[str, Any]]) -> str:
    if not hits:
        return "I could not find relevant passages in this book for that question yet."
    lead = hits[0]
    chapter = lead.get("chapter") or "this book"
    snippet = lead.get("snippet") or lead.get("text") or ""
    parts = [
        f"Based on passages retrieved from {chapter}, here is a grounded draft answer.",
        "",
        f"Question: {question.strip()}",
        "",
        f"Most relevant excerpt: “{snippet}”",
    ]
    if len(hits) > 1:
        parts.append("")
        parts.append(f"({len(hits) - 1} additional passage(s) were retrieved for context.)")
    return "\n".join(parts)


def query_passages(
    root: Path,
    book_id: str,
    question: str,
    *,
    top_k: int = 3,
    embedder: TextEmbedder | None = None,
    use_model: bool = False,
    model: str = DEFAULT_ANSWER_MODEL,
) -> dict[str, Any]:
    path = index_path_for_book(root, book_id)
    passages = read_passages(path)
    if not passages:
        raise BookChatNotFoundError(f"No passage index for book_id={book_id}")

    emb = embedder or _default_embedder()
    query_vec = emb.embed(question)
    hits = retrieve_top_k(query_vec, passages, top_k=top_k)
    citations = [_citation_from_hit(h) for h in hits]

    fallback_used = False
    model_provider = RETRIEVAL_ONLY_PROVIDER

    if use_model:
        context_blocks = []
        for h in hits:
            context_blocks.append(
                f"[{h.get('passage_id')}] ({h.get('chapter')})\n{h.get('text') or h.get('snippet')}"
            )
        prompt = (
            "Answer the user's question using only the book passages below. "
            "If the passages do not support an answer, say so.\n\n"
            f"Question: {question}\n\nPassages:\n" + "\n\n".join(context_blocks)
        )
        gateway = ask_via_hermes_codex(prompt, model=model)
        model_provider = gateway.provider
        fallback_used = gateway.fallback_used
        if gateway.ok and gateway.text.strip():
            answer = gateway.text.strip()
        else:
            fallback_used = True
            model_provider = RETRIEVAL_ONLY_PROVIDER
            answer = _retrieval_only_answer(question, hits)
    else:
        answer = _retrieval_only_answer(question, hits)

    return {
        "ok": True,
        "book_id": book_id,
        "answer": answer,
        "citations": citations,
        "retrieved_passages": hits,
        "model_provider": model_provider,
        "model": model if use_model else DEFAULT_ANSWER_MODEL,
        "fallback_used": fallback_used,
    }
