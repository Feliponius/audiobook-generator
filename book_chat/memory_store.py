"""JSONL-backed book-specific memory storage for Book Chat."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from book_chat.index_store import read_passages, write_passages

VALID_SOURCES = frozenset({"user", "assistant", "insight"})


def memory_path_for_book(root: Path, book_id: str) -> Path:
    return root / "library" / "book_chat" / book_id / "memories.jsonl"


def read_memories(path: Path) -> list[dict[str, Any]]:
    return read_passages(path)


def write_memories(path: Path, records: list[dict[str, Any]]) -> None:
    write_passages(path, records)


def list_memories(root: Path, book_id: str) -> list[dict[str, Any]]:
    return read_memories(memory_path_for_book(root, book_id))


def save_memory(root: Path, book_id: str, text: str, *, source: str = "user") -> dict[str, Any]:
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
