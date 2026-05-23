"""JSONL-backed book-specific memory storage for Book Chat."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from book_chat.index_store import read_passages, write_passages

VALID_SOURCES = frozenset({"user", "assistant", "insight"})
_CITATION_KEYS = ("passage_id", "chapter", "snippet")
_MAX_SNIPPET_LEN = 1000


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _sanitize_citations(citations: Any) -> list[dict[str, str]] | None:
    if not isinstance(citations, list):
        return None
    out: list[dict[str, str]] = []
    for item in citations:
        if not isinstance(item, dict):
            continue
        row: dict[str, str] = {}
        for key in _CITATION_KEYS:
            val = item.get(key)
            if not isinstance(val, str):
                continue
            cleaned = val.strip()
            if not cleaned:
                continue
            if key == "snippet" and len(cleaned) > _MAX_SNIPPET_LEN:
                cleaned = cleaned[:_MAX_SNIPPET_LEN]
            row[key] = cleaned
        if row:
            out.append(row)
    return out or None


def memory_path_for_book(root: Path, book_id: str) -> Path:
    return root / "library" / "book_chat" / book_id / "memories.jsonl"


def read_memories(path: Path) -> list[dict[str, Any]]:
    return read_passages(path)


def write_memories(path: Path, records: list[dict[str, Any]]) -> None:
    write_passages(path, records)


def list_memories(root: Path, book_id: str) -> list[dict[str, Any]]:
    return read_memories(memory_path_for_book(root, book_id))


def save_memory(
    root: Path,
    book_id: str,
    text: str,
    *,
    source: str = "user",
    title: str | None = None,
    question: str | None = None,
    action: str | None = None,
    citations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_source = (source or "user").strip().lower()
    if normalized_source not in VALID_SOURCES:
        raise ValueError(f"invalid source: {source}")
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("missing text")
    record: dict[str, Any] = {
        "memory_id": str(uuid.uuid4()),
        "book_id": book_id,
        "text": cleaned,
        "source": normalized_source,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    optional_title = _optional_str(title)
    if optional_title:
        record["title"] = optional_title
    optional_question = _optional_str(question)
    if optional_question:
        record["question"] = optional_question
    optional_action = _optional_str(action)
    if optional_action:
        record["action"] = optional_action
    sanitized_citations = _sanitize_citations(citations)
    if sanitized_citations:
        record["citations"] = sanitized_citations
    path = memory_path_for_book(root, book_id)
    memories = read_memories(path)
    memories.append(record)
    write_memories(path, memories)
    return record


def delete_memory(root: Path, book_id: str, memory_id: str) -> bool:
    path = memory_path_for_book(root, book_id)
    memories = read_memories(path)
    filtered = [m for m in memories if m.get("memory_id") != memory_id]
    if len(filtered) == len(memories):
        return False
    write_memories(path, filtered)
    return True
