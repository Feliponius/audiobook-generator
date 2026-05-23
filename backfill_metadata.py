#!/usr/bin/env python3
"""Backfill metadata + cover for existing library books."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from monitor_server import (
    _download_cover_bytes,
    _enrich_from_google_books,
    extract_epub_metadata,
    library_paths,
    read_catalog,
    write_catalog,
)


def backfill_book(book_id: str) -> None:
    catalog = read_catalog(ROOT)
    books = catalog.get("books", [])
    book = next((b for b in books if b.get("id") == book_id), None)
    if not book:
        print(f"Book {book_id} not found")
        return

    epub_path = ROOT / book["epub_rel_path"]
    if not epub_path.exists():
        print(f"EPUB not found: {epub_path}")
        return

    raw_name = book.get("source_filename", "")
    print(f"Processing: {book.get('title')} by {book.get('author')}")
    print(f"  EPUB: {epub_path}")

    title, author, cover_bytes, extra = extract_epub_metadata(epub_path, raw_name)
    print(f"  Extracted title: {title}")
    print(f"  Extracted author: {author}")
    print(f"  Embedded cover: {'YES' if cover_bytes else 'NO'}")

    # If no embedded cover, try Google Books
    if not cover_bytes and title:
        print("  Trying Google Books...")
        enriched = _enrich_from_google_books(title, author)
        if enriched.get("cover_url"):
            print(f"  Found cover URL: {enriched['cover_url']}")
            cover_bytes = _download_cover_bytes(enriched["cover_url"])
            print(f"  Downloaded cover: {'YES' if cover_bytes else 'NO'}")
        if enriched.get("title"):
            title = enriched["title"]
        if enriched.get("author"):
            author = enriched["author"]
        extra.update({k: v for k, v in enriched.items() if k != "cover_url"})

    # Save cover if found
    cover_rel = book.get("cover_rel_path")
    if cover_bytes and not cover_rel:
        lib_base, uploads, covers, runs = library_paths(ROOT)
        covers.mkdir(parents=True, exist_ok=True)
        ext = ".jpg"
        if cover_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            ext = ".png"
        elif cover_bytes[:4] == b"GIF8":
            ext = ".gif"
        elif cover_bytes[:4] == b"RIFF" and len(cover_bytes) >= 12 and cover_bytes[8:12] == b"WEBP":
            ext = ".webp"
        cover_path = covers / f"{book_id}{ext}"
        cover_path.write_bytes(cover_bytes)
        cover_rel = str(cover_path.relative_to(ROOT))
        print(f"  Saved cover: {cover_rel}")
    elif cover_rel:
        print(f"  Cover already exists: {cover_rel}")
    else:
        print("  No cover found")

    # Update record
    book["title"] = title or book.get("title", "")
    book["author"] = author or book.get("author", "")
    book["cover_rel_path"] = cover_rel
    if extra:
        existing_meta = book.get("metadata", {})
        existing_meta.update(extra)
        book["metadata"] = existing_meta
        print(f"  Metadata added: {list(extra.keys())}")

    write_catalog(ROOT, catalog)
    print("  Catalog updated")


if __name__ == "__main__":
    # Backfill the Thinking, Fast and Slow book
    backfill_book("1123554b-99dd-4582-bc6c-ad9b267fb218")
