from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ebooklib import epub

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import epub_to_audiobook  # noqa: E402
import monitor_server  # noqa: E402


class ChapterTitleAndRetentionTests(unittest.TestCase):
    def test_extract_chapters_prefers_toc_section_title_over_epub_packaging_filename(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "book.epub"
            book = epub.EpubBook()
            book.set_identifier("packaged-title-test")
            book.set_title("Packaged Title Test")
            book.set_language("en")

            item = epub.EpubHtml(
                title="Benn_9781595550552_epub_c11_r1",
                file_name="Benn_9781595550552_epub_c11_r1.xhtml",
                lang="en",
            )
            item.content = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<html xmlns="http://www.w3.org/1999/xhtml">'
                '<head><title>Benn_9781595550552_epub_c11_r1</title></head>'
                '<body><p>This is real chapter text long enough to be extracted.</p></body></html>'
            ).encode("utf-8")
            book.add_item(item)
            book.toc = ((epub.Section("Chapter 1: Westward the Course (1492–1607)", href=item.file_name), []),)
            book.spine = ["nav", item]
            book.add_item(epub.EpubNav())
            book.add_item(epub.EpubNcx())
            epub.write_epub(str(path), book, {})

            _, chapters = epub_to_audiobook.extract_chapters(path)

            self.assertEqual(chapters[0].title, "Chapter 1: Westward the Course (1492–1607)")

    def test_monitor_summary_applies_epub_toc_titles_to_running_status(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            epub_path = root / "upload.epub"
            book = epub.EpubBook()
            book.set_identifier("status-title-test")
            book.set_title("Status Title Test")
            book.set_language("en")
            item = epub.EpubHtml(
                title="Benn_9781595550552_epub_c12_r1",
                file_name="Benn_9781595550552_epub_c12_r1.html",
                lang="en",
            )
            item.content = b'<html><body><p>Chapter text.</p></body></html>'
            book.add_item(item)
            book.toc = ((epub.Section("Chapter 2: A City Upon a Hill (1607–1765)", href=item.file_name), []),)
            book.spine = ["nav", item]
            book.add_item(epub.EpubNav())
            book.add_item(epub.EpubNcx())
            epub.write_epub(str(epub_path), book, {})

            run_dir = root / "library" / "runs" / "book-id" / "status-title-test"
            run_dir.mkdir(parents=True)
            (run_dir / "status.json").write_text(
                '{"source":"%s","current":{"chapter_index":1,"chapter_title":"Benn_9781595550552_epub_c12_r1","chapter_slug":"001-benn-9781595550552-epub-c12-r1"},"chapters":[{"index":1,"title":"Benn_9781595550552_epub_c12_r1","slug":"001-benn-9781595550552-epub-c12-r1","status":"running","total_chunks":10,"tts_completed_chunks":3}],"progress":{}}'
                % str(epub_path),
                encoding="utf-8",
            )

            summary = monitor_server.run_summary(run_dir)

            self.assertEqual(summary["chapters"][0]["title"], "Chapter 2: A City Upon a Hill (1607–1765)")
            self.assertEqual(summary["current"]["chapter_title"], "Chapter 2: A City Upon a Hill (1607–1765)")

    def test_cleanup_intermediate_audio_files_keeps_final_book_and_status(self) -> None:
        with TemporaryDirectory() as td:
            book_dir = Path(td) / "book"
            (book_dir / "chapters" / "001-test").mkdir(parents=True)
            (book_dir / "chunks").mkdir()
            (book_dir / "chapters" / "001-test" / "chunk-001.m4a").write_bytes(b"chunk")
            final = book_dir / "book.m4b"
            manifest = book_dir / "manifest.json"
            status = book_dir / "status.json"
            events = book_dir / "events.jsonl"
            for p in (final, manifest, status, events):
                p.write_text("keep", encoding="utf-8")

            result = epub_to_audiobook.cleanup_intermediate_audio_files(book_dir, keep={final, manifest, status, events})

            self.assertFalse((book_dir / "chapters").exists())
            self.assertFalse((book_dir / "chunks").exists())
            self.assertTrue(final.exists())
            self.assertEqual(result["policy"], "delete_intermediates_after_complete")


if __name__ == "__main__":
    unittest.main()
