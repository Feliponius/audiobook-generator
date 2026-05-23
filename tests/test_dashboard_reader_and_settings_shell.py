from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = REPO_ROOT / "dashboard" / "index.html"


class DashboardShellTests(unittest.TestCase):
    def test_dashboard_includes_jszip_and_arraybuffer_reader_path(self) -> None:
        html = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn("jszip.min.js", html)
        self.assertIn("arrayBuffer()", html)
        self.assertIn("const book = ePub(epubData);", html)

    def test_settings_ui_mentions_script_only_and_workers(self) -> None:
        html = DASHBOARD.read_text(encoding="utf-8")
        self.assertNotIn('id="setWorkers"', html)
        self.assertNotIn('id="setRewrite"', html)
        self.assertIn("script-only cleanup", html)
        self.assertIn("2 Kokoro workers", html)

    def test_reader_shell_playbooks_markers_and_reading_contrast_css(self) -> None:
        html = DASHBOARD.read_text(encoding="utf-8")
        self.assertNotIn('id="readerPrev"', html)
        self.assertNotIn('id="readerNext"', html)
        self.assertNotIn('id="readerToc"', html)
        self.assertIn('data-reader-shell="playbooks-v1"', html)
        self.assertIn('id="readerContentsBtn"', html)
        self.assertIn('id="readerTapPrev"', html)
        self.assertIn('id="readerTapNext"', html)
        self.assertIn('id="readerThemeBtn"', html)
        self.assertIn('data-reading-theme="night"', html)
        self.assertIn('#readerScreen[data-reading-theme="night"] #bookViewer.reader-surface', html)
        self.assertIn('#readerScreen[data-reading-theme="day"] #bookViewer.reader-surface', html)
        self.assertIn("color: '#ffffff'", html)
        self.assertIn("color: '#000000'", html)

    def test_delete_book_flow_copy_in_dashboard(self) -> None:
        html = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn('id="btnDeleteBook"', html)
        self.assertIn('permanently remove its EPUB, cover', html)

    def test_completed_chapter_prefers_run_final_when_available(self) -> None:
        html = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn("isCompleted && runFinal", html)
        self.assertIn("primary = runFinal; srcKind = 'final'; transport = 'book'", html)

    def test_dashboard_timeline_helpers_marker(self) -> None:
        html = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn('data-timeline-helpers="absolute-v1"', html)
        self.assertIn('data-timeline-derive-offsets="1"', html)
        self.assertIn("timeline-normalize: when start_s/end_s missing", html)
        self.assertIn("function chapterTimeline(", html)
        self.assertIn("function resolveAbsoluteToChapter(", html)
        self.assertIn("function resolveChapterToAbsolute(", html)

    def test_book_detail_sections_collapsible_defaults(self) -> None:
        html = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn('data-book-detail-sections="collapsible-v1"', html)
        self.assertIn('<details class="detail-section" id="progressSection" open>', html)
        self.assertIn('<details class="detail-section" id="chapterListSection">', html)
        self.assertIn('id="chapterSelectorSummary"', html)
        self.assertIn('class="chapter-selector-legend"', html)
        self.assertIn('<details class="detail-section" id="bmSection">', html)
        self.assertIn('<details class="detail-section" id="notesSection">', html)

    def test_expanded_player_uses_custom_audio_sheet(self) -> None:
        html = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn('data-player-sheet="audio-first-v1"', html)
        self.assertIn('class="sheet-media-slot"', html)
        self.assertIn('id="sheetSeek"', html)
        self.assertIn('id="sheetPlayBtn"', html)
        self.assertIn('id="sheetSkipBack"', html)
        self.assertIn('id="sheetSkipFwd"', html)
        self.assertIn('id="sheetPrevCh"', html)
        self.assertIn('id="sheetNextCh"', html)
        self.assertIn('id="miniBookmarkBtn"', html)
        self.assertIn('id="readerDockBookmarkBtn"', html)
        self.assertIn('id="sheetBookmarkBtn"', html)
        self.assertIn('function syncSheetPlayerUI(', html)
        self.assertIn('function findPrevPlayableChapter(', html)
        self.assertIn('<video id="hlsVideo" playsinline></video>', html)
        self.assertNotIn('controls controlsList', html)

    def test_open_book_detail_preserves_playback_while_browsing_other_books(self) -> None:
        """Passive #/book/<other-id> navigation must not stop or replace another book's player."""
        html = DASHBOARD.read_text(encoding="utf-8")
        self.assertNotIn(
            "if (state.playerSession && state.playerSession.id !== id) stopPlayer();",
            html,
        )
        self.assertIn("const preserveActivePlayback = !!", html)
        self.assertIn("!opts.activatePlayback", html)
        self.assertIn("if (!keepMedia && !preserveActivePlayback)", html)
        self.assertIn("openBookDetail(bookId, { activatePlayback: true })", html)
        self.assertIn("const playingThisBook = state.playerSession && state.playerSession.id === id", html)

    def test_book_detail_listening_actions_and_selector_copy_are_explicit(self) -> None:
        html = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn("function listenActionCopy(b, id)", html)
        self.assertIn("'Open current audio'", html)
        self.assertIn("'Play this audiobook'", html)
        self.assertIn("'Resume this audiobook'", html)
        self.assertIn("summary.textContent = 'Ch. ' + (activeChapter ? activeChapter.index : '—')", html)

    def test_book_chat_ui_markers_and_learning_actions(self) -> None:
        html = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn('data-book-chat-ui="v1"', html)
        self.assertIn('id="bookChatPanel"', html)
        self.assertIn('id="bookChatQuestion"', html)
        self.assertIn('id="bookChatSendBtn"', html)
        self.assertIn('id="bookChatCitations"', html)
        self.assertIn('id="btnBookChat"', html)
        self.assertIn("Ask this book", html)
        self.assertIn("Explain this another way", html)
        self.assertIn("Ask me Socratic questions", html)
        self.assertIn("Challenge my assumptions", html)
        self.assertIn("Give me a real-life example", html)
        self.assertIn("Turn this into a practice exercise", html)
        self.assertIn("Save this insight", html)
        self.assertIn('id="bookChatIndexStatus"', html)
        self.assertIn('id="bookChatIndexBtn"', html)
        self.assertIn("/api/library/book-chat/query", html)
        self.assertIn("/api/library/book-chat/memory", html)
        self.assertIn("/api/library/book-chat/index-status", html)
        self.assertIn("/api/library/book-chat/auto-index", html)
        self.assertIn("Could not check index status. You can still try indexing this book.", html)
        self.assertIn("first run can take 5–10 minutes", html)
        self.assertIn("$('bookChatIndexBtn').classList.remove('hidden');", html)

    def test_audiobook_chapter_labels_use_api_one_based_index(self) -> None:
        """run.chapters[].index is already 1-based; do not add 1 for display or mini-player hints."""
        html = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn("num.textContent = ch.index;", html)
        self.assertIn("ch.title || ('Chapter ' + ch.index)", html)
        self.assertIn("'Ch. ' + b.listen_chapter_index + ' · '", html)
        self.assertNotIn("ch.index + 1", html)
        self.assertNotIn("listen_chapter_index + 1", html)


if __name__ == "__main__":
    unittest.main()
