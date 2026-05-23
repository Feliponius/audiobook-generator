"""Shared EPUB fixtures for unit tests."""

from __future__ import annotations

from pathlib import Path

from ebooklib import epub


def write_tiny_epub(path: Path, chapters: list[tuple[str, str]]) -> None:
    book = epub.EpubBook()
    book.set_identifier("test-book-chat-epub")
    book.set_title("Test Book")
    book.set_language("en")

    items: list[epub.EpubHtml] = []
    for i, (title, body) in enumerate(chapters):
        item = epub.EpubHtml(
            title=title,
            file_name=f"chapter_{i + 1}.xhtml",
            lang="en",
        )
        item.content = (
            f'<?xml version="1.0" encoding="utf-8"?>'
            f'<html xmlns="http://www.w3.org/1999/xhtml">'
            f"<head><title>{title}</title></head>"
            f"<body><h1>{title}</h1><p>{body}</p></body></html>"
        ).encode("utf-8")
        book.add_item(item)
        items.append(item)

    book.toc = items
    book.spine = ["nav"] + items
    book.add_item(epub.EpubNav())
    book.add_item(epub.EpubNcx())
    epub.write_epub(str(path), book, {})
