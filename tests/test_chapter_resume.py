from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import epub_to_audiobook as eta


class ChapterResumeTests(unittest.TestCase):
    """detect_completed_chapters() resume detection."""

    def test_detect_all_missing_when_no_dirs(self):
        completed = eta.detect_completed_chapters(
            Path("/nonexistent"),
            total_chunks_map={1: 3},
            chapter_slugs={1: "001-cover"},
        )
        self.assertEqual(completed, set())

    def test_detect_single_complete_chapter(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            ch_dir = root / "chapters" / "001-cover-page"
            ch_dir.mkdir(parents=True)
            for i in range(1, 4):
                (ch_dir / f"chunk-{i:03d}.wav").write_text("fake wav")
            (root / "chapters" / "001-cover-page.wav").write_text("fake wav")
            (root / "chapters" / "001-cover-page.m4a").write_text("fake")

            completed = eta.detect_completed_chapters(
                root,
                total_chunks_map={1: 3, 2: 5},
                chapter_slugs={1: "001-cover-page", 2: "002-title-page"},
            )
            self.assertEqual(completed, {1})

    def test_detect_incomplete_chapter_skipped(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            ch_dir = root / "chapters" / "001-cover-page"
            ch_dir.mkdir(parents=True)
            # Only 1 of 3 WAVs
            (ch_dir / "chunk-001.wav").write_text("fake wav")

            completed = eta.detect_completed_chapters(
                root,
                total_chunks_map={1: 3},
                chapter_slugs={1: "001-cover-page"},
            )
            self.assertEqual(completed, set())

    def test_detect_complete_via_hls(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            ch_dir = root / "chapters" / "001-cover-page"
            ch_dir.mkdir(parents=True)
            for i in range(1, 3):
                (ch_dir / f"chunk-{i:03d}.wav").write_text("fake wav")
            # HLS playlist instead of chapter WAV/M4A
            (ch_dir / "chapter-001.m3u8").write_text("#EXTM3U\n")

            completed = eta.detect_completed_chapters(
                root,
                total_chunks_map={1: 2},
                chapter_slugs={1: "001-cover-page"},
            )
            self.assertEqual(completed, {1})

    def test_stale_old_and_incomplete_new_ignored(self):
        """Old Benn-named dir from prior run + incomplete clean-name dir = nothing complete."""
        with TemporaryDirectory() as td:
            root = Path(td)
            # Old run dir (Benn name, fully complete)
            old = root / "chapters" / "001-benn-9781595550552-epub-c1-r1"
            old.mkdir(parents=True)
            for i in range(1, 4):
                (old / f"chunk-{i:03d}.wav").write_text("fake")
            (root / "chapters" / "001-benn-9781595550552-epub-c1-r1.wav").write_text("fake")
            (root / "chapters" / "001-benn-9781595550552-epub-c1-r1.m4a").write_text("fake")

            # New run dir (clean name, only 1 of 3 chunks)
            new = root / "chapters" / "001-cover-page"
            new.mkdir(parents=True)
            (new / "chunk-001.wav").write_text("fake")

            completed = eta.detect_completed_chapters(
                root,
                total_chunks_map={1: 3, 2: 5},
                chapter_slugs={1: "001-cover-page", 2: "002-title-page"},
            )
            # Nothing should be complete — the current slug dir (cover-page) isn't done
            self.assertEqual(completed, set())

    def test_detect_multiple_complete(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            for slug, idx, nchunks in [
                ("001-cover", 1, 2),
                ("002-title", 2, 3),
                ("003-body", 3, 4),
            ]:
                ch_dir = root / "chapters" / slug
                ch_dir.mkdir(parents=True)
                for i in range(1, nchunks + 1):
                    (ch_dir / f"chunk-{i:03d}.wav").write_text("fake")
                (root / "chapters" / f"{slug}.wav").write_text("fake")
                (root / "chapters" / f"{slug}.m4a").write_text("fake")

            # Chapter 4 not on disk
            completed = eta.detect_completed_chapters(
                root,
                total_chunks_map={1: 2, 2: 3, 3: 4, 4: 1},
                chapter_slugs={1: "001-cover", 2: "002-title", 3: "003-body", 4: "004-missing"},
            )
            self.assertEqual(completed, {1, 2, 3})


if __name__ == "__main__":
    unittest.main()
