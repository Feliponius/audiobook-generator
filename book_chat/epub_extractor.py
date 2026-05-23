"""Extract searchable passage chunks from library EPUB files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from epub_to_audiobook import extract_chapters

MIN_CHUNK_CHARS = 80


def _merge_tiny_chunks(chunks: list[str], *, min_chars: int = MIN_CHUNK_CHARS) -> list[str]:
    if not chunks:
        return []
    out: list[str] = []
    for chunk in chunks:
        text = chunk.strip()
        if not text:
            continue
        if len(text) < min_chars and out:
            out[-1] = f"{out[-1]} {text}".strip()
        elif len(text) < min_chars and not out:
            out.append(text)
        else:
            out.append(text)
    return out


def _chunk_text_with_overlap(
    text: str,
    *,
    max_chars: int,
    overlap_chars: int,
) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        if end < len(normalized):
            window = normalized[start:end]
            break_at = window.rfind(" ", max(0, len(window) - max(80, max_chars // 5)))
            if break_at >= max_chars // 4:
                end = start + break_at
        piece = normalized[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(normalized):
            break
        next_start = end - overlap_chars
        if next_start <= start:
            next_start = end
        start = next_start
    return _merge_tiny_chunks(chunks)


def passages_from_chapters(
    chapters: list[Any],
    *,
    max_chars: int = 1200,
    overlap_chars: int = 150,
) -> list[dict[str, Any]]:
    """Build passage dicts from ``extract_chapters`` chapter objects."""
    passages: list[dict[str, Any]] = []
    for chapter in chapters:
        chunks = _chunk_text_with_overlap(
            chapter.text,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        )
        for chunk_index, chunk in enumerate(chunks):
            passages.append(
                {
                    "chapter": chapter.title,
                    "text": chunk,
                    "chapter_index": chapter.index,
                    "source": chapter.source,
                    "chunk_index": chunk_index,
                }
            )
    return passages


def extract_passages_from_epub(
    epub_path: Path,
    *,
    max_chars: int = 1200,
    overlap_chars: int = 150,
) -> list[dict[str, Any]]:
    """Return passage dicts with chapter metadata and chunked text from an EPUB."""
    _book_title, chapters = extract_chapters(epub_path)
    return passages_from_chapters(
        chapters,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
