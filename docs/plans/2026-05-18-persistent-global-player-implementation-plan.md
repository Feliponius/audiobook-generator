# Persistent Global Audiobook Player Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Upgrade the dashboard from a book-detail-scoped player into a persistent global audiobook player that keeps playing across Library, Book, Settings, and Reader navigation while showing the active book, chapter, and progress.

**Architecture:** Promote playback ownership from `openBookDetail()` into one app-root player module inside `dashboard/index.html`. Keep a single media element, one HLS attachment, and one shared `state.player` object. Book detail, library cards, and the reader become command surfaces that render metadata and dispatch play/open/seek actions instead of owning media lifecycle.

**Tech Stack:** Existing single-file dashboard SPA (`dashboard/index.html`), existing Python API server (`monitor_server.py`), hls.js, browser Media Session API, Python unittest/pytest test suite.

---

## Verified current state

These facts were checked in the current codebase before writing this plan:

- The current playback markup is page-scoped inside `#bookScreen` at `dashboard/index.html:914-917`.
- The current playback lifecycle is owned by `openBookDetail()` at `dashboard/index.html:1573-1693`.
- The route handler currently destroys playback whenever the route is not `book` at `dashboard/index.html:2027-2045`.
- HLS attachment is already isolated in `attachHls()` at `dashboard/index.html:1222-1239`.
- Existing persisted listening fields already exist in the catalog/API and are patchable via `/api/library/patch` in `monitor_server.py:1379-1517`:
  - `listen_time_s`
  - `listen_chapter_index`
  - `listen_progress_hint`
  - `listen_src`
  - `listen_duration_s`
- Existing chapter switching and auto-advance logic already exists at:
  - `dashboard/index.html:1280-1308` for next playable chapter polling/advance
  - `dashboard/index.html:1468-1541` for chapter list rendering and click-to-play
- Existing dashboard tests live in:
  - `tests/test_dashboard_reader_and_settings_shell.py`
  - `tests/test_monitor_server_phase2_api.py`

## Product decisions locked by this plan

- Keep one persistent player for the whole SPA.
- Show a bottom mini-player above bottom navigation on Library, Book, and Settings routes.
- Hide the bottom mini-player on the immersive reader route and replace it with a slimmer in-reader audio pill/button that opens the same now-playing sheet.
- Preserve existing HLS/live chapter behavior and existing resume fields.
- Use a custom audiobook UI over a root-level `<audio>` element unless a proven blocker appears during implementation.
- Add Media Session metadata/actions for Android/lock-screen/headset friendliness.

## Non-goals for the first implementation pass

- No backend schema redesign.
- No playlist/queue across multiple books.
- No sleep timer yet.
- No waveform visualizer.
- No service worker/offline download changes.

---

### Task 1: Add tests that lock the new root-level player shell

**Objective:** Create failing tests that define the new persistent-player structure before moving code.

**Files:**
- Modify: `tests/test_dashboard_reader_and_settings_shell.py`
- Modify: `dashboard/index.html`

**Step 1: Write failing test**

Add assertions that require these strings in `dashboard/index.html`:

```python
def test_dashboard_has_global_player_shell_markers(self) -> None:
    html = DASHBOARD.read_text(encoding="utf-8")
    self.assertIn('id="globalPlayerShell"', html)
    self.assertIn('id="globalPlayerBar"', html)
    self.assertIn('id="nowPlayingSheet"', html)
    self.assertIn('id="globalAudio"', html)
    self.assertIn('state.player = {', html)
```

**Step 2: Run test to verify failure**

Run:

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k global_player_shell_markers -v
```

Expected: FAIL because the new shell markers do not exist yet.

**Step 3: Write minimal implementation**

Add placeholder root-level markup near the bottom nav area and add an empty `state.player` object in the script.

**Step 4: Run test to verify pass**

Run:

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k global_player_shell_markers -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_dashboard_reader_and_settings_shell.py dashboard/index.html
git commit -m "test: lock global player shell markers"
```

---

### Task 2: Add a failing test that prevents route teardown from killing active playback

**Objective:** Codify the main architectural requirement: navigation should not destroy active playback outside the book screen.

**Files:**
- Modify: `tests/test_dashboard_reader_and_settings_shell.py`
- Modify: `dashboard/index.html`

**Step 1: Write failing test**

Add assertions that the route handler no longer contains the old destructive branch and instead uses an allowlist-style visibility update:

```python
def test_route_ui_no_longer_clears_media_on_non_book_routes(self) -> None:
    html = DASHBOARD.read_text(encoding="utf-8")
    self.assertNotIn("if (r.name !== 'book') {", html)
    self.assertNotIn("v.pause();", html)
    self.assertIn("syncPlayerRouteVisibility(r);", html)
```

**Step 2: Run test to verify failure**

Run:

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k route_ui_no_longer_clears_media -v
```

Expected: FAIL because the old teardown block still exists.

**Step 3: Write minimal implementation**

Introduce a new `syncPlayerRouteVisibility(route)` function and change `routeUI()` to call it instead of pausing/destroying the active player whenever the user leaves `#/book/:id`.

**Step 4: Run test to verify pass**

Run:

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k route_ui_no_longer_clears_media -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_dashboard_reader_and_settings_shell.py dashboard/index.html
git commit -m "test: lock persistent playback across routes"
```

---

### Task 3: Introduce root-level player markup and visual shell

**Objective:** Move the player UI out of book detail and create the persistent shell.

**Files:**
- Modify: `dashboard/index.html:914-955` (replace page-scoped player panel and add root-level player shell)
- Test: `tests/test_dashboard_reader_and_settings_shell.py`

**Step 1: Write failing test**

Expand the shell test to require mini-player and sheet controls:

```python
self.assertIn('id="playerBarTitle"', html)
self.assertIn('id="playerBarChapter"', html)
self.assertIn('id="playerTogglePlay"', html)
self.assertIn('id="playerSeek"', html)
self.assertIn('id="playerChapterList"', html)
self.assertIn('id="readerAudioDock"', html)
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k player -v
```

Expected: FAIL.

**Step 3: Write minimal implementation**

Create this structure at app root:

- persistent mini-player shell `#globalPlayerShell`
- compact bar `#globalPlayerBar`
- hidden expanded sheet `#nowPlayingSheet`
- root media element `#globalAudio`
- reader-only compact trigger `#readerAudioDock`

The mini-player should be hidden by default until audio is loaded.

**Step 4: Run test to verify pass**

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k player -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add dashboard/index.html tests/test_dashboard_reader_and_settings_shell.py
git commit -m "feat: add root-level persistent player shell"
```

---

### Task 4: Create shared player state and root media controller

**Objective:** Build one app-level playback engine.

**Files:**
- Modify: `dashboard/index.html:957-1739`
- Test: `tests/test_dashboard_reader_and_settings_shell.py`

**Step 1: Write failing test**

Add assertions for core controller functions:

```python
self.assertIn("function ensurePlayerState()", html)
self.assertIn("function loadPlayerForBook(", html)
self.assertIn("function syncPlayerUI()", html)
self.assertIn("function bindGlobalAudioEvents()", html)
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k controller -v
```

Expected: FAIL.

**Step 3: Write minimal implementation**

Refactor the script so `state.player` owns:

```javascript
state.player = {
  bookId: null,
  title: '',
  author: '',
  coverUrl: '',
  chapterIndex: null,
  chapterTitle: '',
  src: null,
  srcKind: null,
  duration: null,
  currentTime: 0,
  isPlaying: false,
  isExpanded: false,
  hls: null,
  advancePoll: null,
  saveTimer: null,
};
```

Implement these controller responsibilities:
- choose media source for a chapter
- attach/detach HLS on the root audio element
- update UI labels/seekbar/time labels
- preserve state when routes change
- only destroy playback on explicit stop/reset/new-book load, not navigation

**Step 4: Run test to verify pass**

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k controller -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add dashboard/index.html tests/test_dashboard_reader_and_settings_shell.py
git commit -m "feat: add global player controller"
```

---

### Task 5: Refactor book detail into a command surface instead of a lifecycle owner

**Objective:** Make `openBookDetail()` render information and dispatch player commands without owning the audio element.

**Files:**
- Modify: `dashboard/index.html:1573-1739`
- Test: `tests/test_dashboard_reader_and_settings_shell.py`

**Step 1: Write failing test**

Add assertions that `openBookDetail()` no longer manipulates `hlsVideo` and now calls player helpers instead:

```python
self.assertNotIn("const v = $('hlsVideo');", html)
self.assertIn("loadPlayerForBook(id", html)
self.assertIn("syncBookDetailPlaybackState(b);", html)
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k openBookDetail -v
```

Expected: FAIL.

**Step 3: Write minimal implementation**

In `openBookDetail()`:
- remove direct media element setup/teardown
- keep metadata rendering, notes, bookmarks, generation evidence, and chapter list rendering
- convert chapter row clicks and `Play audiobook` to controller calls such as:
  - `loadPlayerForBook(id, { autoplay: true })`
  - `playBookChapter(id, ch.index, { autoplay: true })`
- add a small “Open player” / “Now playing” affordance if this book is already active

**Step 4: Run test to verify pass**

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k openBookDetail -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add dashboard/index.html tests/test_dashboard_reader_and_settings_shell.py
git commit -m "refactor: make book detail use global player"
```

---

### Task 6: Move progress saving and auto-advance into the global controller

**Objective:** Keep existing resume behavior and chapter-to-chapter playback after the refactor.

**Files:**
- Modify: `dashboard/index.html:1241-1373`
- Modify: `tests/test_monitor_server_phase2_api.py` (only if additional patch semantics are needed)
- Test: `tests/test_dashboard_reader_and_settings_shell.py`

**Step 1: Write failing test**

Add string-level assertions that the global controller owns save/advance hooks:

```python
self.assertIn("scheduleGlobalListenSave(", html)
self.assertIn("autoAdvancePlayer(state.player.bookId", html)
self.assertIn("patchBook(state.player.bookId", html)
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k listen -v
```

Expected: FAIL.

**Step 3: Write minimal implementation**

- Rename/move the throttled save code so it reads from the root audio element.
- Ensure `timeupdate`, `loadedmetadata`, and `ended` events are bound once on `#globalAudio`.
- Preserve these persisted fields exactly as they work today:
  - `listen_time_s`
  - `listen_chapter_index`
  - `listen_progress_hint`
  - `listen_src`
  - `listen_duration_s`
- Keep existing next-playable-chapter polling for live HLS generation.

**Step 4: Run test to verify pass**

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k listen -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add dashboard/index.html tests/test_dashboard_reader_and_settings_shell.py
[ -f tests/test_monitor_server_phase2_api.py ] && git add tests/test_monitor_server_phase2_api.py || true
git commit -m "feat: move resume and auto-advance into global player"
```

---

### Task 7: Add mini-player interactions, expanded now-playing sheet, and chapter controls

**Objective:** Deliver the core user-facing experience.

**Files:**
- Modify: `dashboard/index.html`
- Test: `tests/test_dashboard_reader_and_settings_shell.py`

**Step 1: Write failing test**

Add assertions for user controls:

```python
self.assertIn('id="playerSkipBack"', html)
self.assertIn('id="playerSkipForward"', html)
self.assertIn('id="playerSpeed"', html)
self.assertIn('id="playerPrevChapter"', html)
self.assertIn('id="playerNextChapter"', html)
self.assertIn('id="playerBookmark"', html)
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k player -v
```

Expected: FAIL.

**Step 3: Write minimal implementation**

Implement:
- mini-player tap expands sheet
- sheet close button collapses sheet
- play/pause button wired to root audio
- ±15s / +30s seek controls
- speed select (1.0, 1.25, 1.5, 1.75, 2.0)
- prev/next playable chapter
- bookmark current listening position from the player sheet
- chapter list in the sheet highlights the active chapter

**Step 4: Run test to verify pass**

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k player -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add dashboard/index.html tests/test_dashboard_reader_and_settings_shell.py
git commit -m "feat: add mini-player and now-playing controls"
```

---

### Task 8: Integrate the reader route without breaking immersion

**Objective:** Keep playback available while reading without forcing the bottom bar over the reader.

**Files:**
- Modify: `dashboard/index.html:819-845`
- Modify: `dashboard/index.html:1909-2025`
- Test: `tests/test_dashboard_reader_and_settings_shell.py`

**Step 1: Write failing test**

Add assertions for the reader dock behavior:

```python
self.assertIn('id="readerAudioDock"', html)
self.assertIn("toggleReaderAudioDock(true)", html)
self.assertIn("toggleReaderAudioDock(false)", html)
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k reader_audio -v
```

Expected: FAIL.

**Step 3: Write minimal implementation**

- Hide `#globalPlayerShell` on `#/read/:id`
- Show `#readerAudioDock` if a player session exists
- Tapping the reader dock opens the now-playing sheet or returns to the active book/player context
- Ensure leaving the reader does not stop audio

**Step 4: Run test to verify pass**

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k reader_audio -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add dashboard/index.html tests/test_dashboard_reader_and_settings_shell.py
git commit -m "feat: integrate persistent audio with reader shell"
```

---

### Task 9: Add Media Session metadata and transport actions

**Objective:** Improve Android lock-screen, headset, and notification transport behavior.

**Files:**
- Modify: `dashboard/index.html`
- Test: `tests/test_dashboard_reader_and_settings_shell.py`

**Step 1: Write failing test**

Add assertions for Media Session hooks:

```python
self.assertIn("if ('mediaSession' in navigator)", html)
self.assertIn("new MediaMetadata(", html)
self.assertIn("navigator.mediaSession.setActionHandler('play'", html)
self.assertIn("navigator.mediaSession.setActionHandler('pause'", html)
self.assertIn("navigator.mediaSession.setActionHandler('previoustrack'", html)
self.assertIn("navigator.mediaSession.setActionHandler('nexttrack'", html)
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k media_session -v
```

Expected: FAIL.

**Step 3: Write minimal implementation**

When a book/chapter loads:
- set title to book title
- set artist to author
- set album/chapter metadata where useful
- set artwork from cover URL when available
- wire play/pause/next/previous handlers into the global controller

**Step 4: Run test to verify pass**

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -k media_session -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add dashboard/index.html tests/test_dashboard_reader_and_settings_shell.py
git commit -m "feat: add media session support for global player"
```

---

### Task 10: Regression-test the dashboard and API behavior

**Objective:** Verify the refactor did not break existing shell and patch behavior.

**Files:**
- Test: `tests/test_dashboard_reader_and_settings_shell.py`
- Test: `tests/test_monitor_server_phase2_api.py`

**Step 1: Run targeted dashboard tests**

Run:

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py -v
```

Expected: PASS.

**Step 2: Run API tests covering read/listen patch persistence**

Run:

```bash
pytest tests/test_monitor_server_phase2_api.py -k "patch or settings or library_book" -v
```

Expected: PASS.

**Step 3: If any test fails, fix the smallest surface**

Likely fixes:
- broken shell marker names
- route visibility logic
- missing existing copy strings expected by tests
- patch payload drift on listen save

**Step 4: Run both suites again**

Run:

```bash
pytest tests/test_dashboard_reader_and_settings_shell.py tests/test_monitor_server_phase2_api.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_dashboard_reader_and_settings_shell.py tests/test_monitor_server_phase2_api.py dashboard/index.html
git commit -m "test: verify persistent player refactor regressions"
```

---

### Task 11: Manual browser verification against the live dashboard

**Objective:** Confirm the UX works in real navigation flows, not just string-level tests.

**Files:**
- No file changes required unless bugs are found.

**Step 1: Start or reuse the local dashboard server**

Run the project’s usual local server command.

**Step 2: Verify these flows manually**

- Start playback from a book page.
- Navigate to Library; audio keeps playing; mini-player remains visible.
- Navigate to Settings; audio keeps playing; mini-player remains visible.
- Enter Reader; bottom mini-player hides; reader audio dock appears; audio continues.
- Return to Book; active chapter/time remain accurate.
- During live HLS generation, chapter auto-advance still works.
- Expanded now-playing sheet opens/closes cleanly.
- Bookmark from now-playing creates a listening bookmark.

**Step 3: Verify persisted resume**

Reload the page or re-open the book.

Expected:
- active chapter restored
- current time restored
- progress hint reflects latest saved position

**Step 4: Fix bugs found during browser verification**

Most likely bugs:
- duplicate event listeners
- seek bar not syncing after chapter switch
- route-specific visibility glitches
- Media Session artwork or chapter label drift

**Step 5: Commit**

```bash
git add dashboard/index.html tests/test_dashboard_reader_and_settings_shell.py tests/test_monitor_server_phase2_api.py
git commit -m "fix: polish persistent global player behavior"
```

---

## Implementation notes and pitfalls

### Keep these existing helpers unless a stronger abstraction clearly wins
- `attachHls()`
- `mediaForChapter()`
- `findNextPlayableChapter()`
- `patchBook()`

### Split the old `openBookDetail()` responsibilities cleanly

Old responsibilities mixed together:
- fetch/render book detail
- configure media source
- bind time listeners
- save progress
- auto-advance
- show/hide player panel

New split:
- `openBookDetail()` = fetch + render + dispatch controls
- global player module = source selection + events + save + advance + transport UI

### Watch for duplicate listener bugs

Because the app is a SPA and `openBookDetail()` re-runs on poll, make sure global audio listeners are bound once. Prefer explicit bind/unbind helpers and sentinel flags.

### Watch for stale route-driven refreshes

The existing book-route polling loop at `dashboard/index.html:2055-2059` should refresh detail metadata without resetting active playback.

### Use the root player as the single truth source

When the active book is open in detail view:
- chapter highlight should derive from `state.player.chapterIndex` if the same book is active
- seek/progress text should derive from the root audio state
- avoid maintaining a second page-local playback truth

---

## Acceptance criteria

This feature is complete when all of the following are true:

- Audio continues playing across Library, Book, and Settings navigation.
- Reader route does not stop playback.
- The app shows the active book and chapter in a persistent player UI.
- Progress, current chapter, and source kind still persist through `/api/library/patch`.
- Live HLS chapter progression still auto-advances correctly.
- The old page-scoped player lifecycle is gone.
- Dashboard and API regression tests pass.
- Manual browser verification confirms the UX matches the intended persistent-player behavior.

---

## Suggested final artifact paths

- Plan: `docs/plans/2026-05-18-persistent-global-player-implementation-plan.md`
- Mockups: `sketches/persistent-player/`

## Execution handoff

Plan complete and saved. Ready to execute using subagent-driven-development — dispatch a fresh subagent per task with spec-compliance review and then code-quality review.