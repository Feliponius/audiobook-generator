"""Tests for EPUB passage extraction used by Book Chat auto-index."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from book_chat.epub_extractor import extract_passages_from_epub
from tests.epub_fixtures import write_tiny_epub


@pytest.fixture
def epub_path(tmp_path: Path) -> Path:
    path = tmp_path / "sample.epub"
    write_tiny_epub(
        path,
        [
            ("Introduction", "Discipline grows through small repeated choices each day."),
            (
                "Chapter Two",
                "Rest and sleep help the mind recover after focused work. "
                "Recovery is part of sustainable learning.",
            ),
        ],
    )
    return path


def test_extract_passages_from_epub_returns_chapter_and_text(epub_path: Path) -> None:
    passages = extract_passages_from_epub(epub_path)
    assert len(passages) >= 2
    chapters = {p["chapter"] for p in passages}
    assert "Introduction" in chapters or any("Introduction" in c for c in chapters)
    assert all(p.get("text") for p in passages)
    assert all("chapter" in p and "text" in p for p in passages)


def test_extract_passages_chunks_long_chapter_text(tmp_path: Path) -> None:
    long_body = "Word " * 400
    path = tmp_path / "long.epub"
    write_tiny_epub(path, [("Long Chapter", long_body.strip())])
    passages = extract_passages_from_epub(path, max_chars=200, overlap_chars=30)
    assert len(passages) > 1
    assert passages[0].get("chunk_index") == 0
    assert all(len(p["text"]) <= 220 for p in passages)
