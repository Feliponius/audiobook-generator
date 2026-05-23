"""Book Chat indexing and grounded query service."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

ProgressCallback = Callable[[dict[str, Any]], None]

from book_chat.embeddings import DEFAULT_BGE_MODEL, LocalBGEEmbedder, TextEmbedder
from book_chat.index_store import index_path_for_book, read_passages, retrieve_top_k, write_passages
from book_chat.model_gateway import ask_via_hermes_codex

DEFAULT_EMBEDDING_MODEL = DEFAULT_BGE_MODEL
DEFAULT_ANSWER_MODEL = "gpt-5.5"
RETRIEVAL_ONLY_PROVIDER = "retrieval_only"


class BookChatNotFoundError(FileNotFoundError):
    """Raised when a book has no passage index on disk."""


class BookChatExtractionError(ValueError):
    """Raised when EPUB passage extraction yields no usable text."""


def get_index_status(root: Path, book_id: str) -> dict[str, Any]:
    path = index_path_for_book(root, book_id)
    passages = read_passages(path)
    if passages:
        model = passages[0].get("embedding_model")
        if not isinstance(model, str) or not model.strip():
            model = DEFAULT_EMBEDDING_MODEL
        return {
            "ok": True,
            "book_id": book_id,
            "indexed": True,
            "passage_count": len(passages),
            "embedding_model": model,
            "index_path": path.relative_to(root).as_posix(),
        }
    return {
        "ok": True,
        "book_id": book_id,
        "indexed": False,
        "passage_count": 0,
    }


def _emit_progress(
    progress_callback: ProgressCallback | None,
    *,
    stage: str,
    message: str,
    current: int = 0,
    total: int = 0,
) -> None:
    if progress_callback is None:
        return
    percent = 0 if total <= 0 else min(100, int(current * 100 / total))
    progress_callback(
        {
            "stage": stage,
            "message": message,
            "current": current,
            "total": total,
            "percent": percent,
        }
    )


def auto_index_book_epub(
    root: Path,
    book_id: str,
    epub_path: Path,
    *,
    force: bool = False,
    embedder: TextEmbedder | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    status = get_index_status(root, book_id)
    if status.get("indexed") and not force:
        return {**status, "status": "already_indexed"}

    from epub_to_audiobook import extract_chapters

    from book_chat.epub_extractor import passages_from_chapters

    _emit_progress(progress_callback, stage="preparing", message="Preparing EPUB…")
    _emit_progress(progress_callback, stage="extracting", message="Extracting chapters…")

    try:
        book_title, chapters = extract_chapters(epub_path)
        raw_passages = passages_from_chapters(chapters)
    except Exception as exc:
        raise BookChatExtractionError(f"EPUB extraction failed: {exc}") from exc
    if not raw_passages:
        raise BookChatExtractionError("No passages extracted from EPUB")

    _emit_progress(progress_callback, stage="chunking", message="Chunking passages…")

    result = index_passages(
        root,
        book_id,
        raw_passages,
        embedder=embedder,
        progress_callback=progress_callback,
    )
    result["status"] = "indexed"
    result["book_title"] = book_title
    return result


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
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    emb = embedder or _default_embedder()
    usable = [
        item
        for item in raw_passages
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    total = len(usable)
    records: list[dict[str, Any]] = []
    embedded = 0
    for i, item in enumerate(raw_passages):
        chapter = str(item.get("chapter") or "").strip()
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        embedded += 1
        _emit_progress(
            progress_callback,
            stage="embedding",
            message=f"Embedding passages {embedded} / {total}…",
            current=embedded,
            total=total,
        )
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
    _emit_progress(progress_callback, stage="saving", message="Saving index…")
    path = index_path_for_book(root, book_id)
    write_passages(path, records)
    count = len(records)
    _emit_progress(
        progress_callback,
        stage="complete",
        message=f"Passage index ready ({count} passages)",
        current=count,
        total=count,
    )
    return {
        "ok": True,
        "book_id": book_id,
        "status": "indexed",
        "passage_count": count,
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
