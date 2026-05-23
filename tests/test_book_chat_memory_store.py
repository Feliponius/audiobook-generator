"""Tests for book_chat JSONL memory storage."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from book_chat.memory_store import (
    delete_memory,
    list_memories,
    memory_path_for_book,
    save_memory,
)


def test_memory_path_for_book_under_library_book_chat() -> None:
    root = Path("/data/repo")
    p = memory_path_for_book(root, "book-abc")
    assert p == root / "library" / "book_chat" / "book-abc" / "memories.jsonl"


def test_save_and_list_memories_round_trip() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        rec = save_memory(root, "b1", "Discipline compounds.", source="insight")
        assert rec["book_id"] == "b1"
        assert rec["text"] == "Discipline compounds."
        assert rec["source"] == "insight"
        assert rec["memory_id"]
        assert rec["created_at"]

        items = list_memories(root, "b1")
        assert len(items) == 1
        assert items[0]["memory_id"] == rec["memory_id"]


def test_save_memory_rejects_invalid_source() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        with pytest.raises(ValueError, match="invalid source"):
            save_memory(root, "b1", "text", source="bogus")


def test_delete_memory_removes_record() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        rec = save_memory(root, "b1", "Keep this.", source="user")
        assert delete_memory(root, "b1", rec["memory_id"]) is True
        assert list_memories(root, "b1") == []


def test_delete_memory_missing_returns_false() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        assert delete_memory(root, "b1", "no-such-id") is False
