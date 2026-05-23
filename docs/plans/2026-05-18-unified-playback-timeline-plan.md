# Unified Audiobook Playback Timeline Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make audiobook playback, chapter jumps, resume, bookmarks, and post-generation behavior consistent from first generated chapter through final completed book output.

**Architecture:** Introduce a canonical *book timeline* model that stores progress and bookmarks in absolute book time, while deriving chapter-relative playback positions from a generated chapter map. During generation, the player resolves absolute time into the currently playable chapter HLS/M4A source. After completion, the player can use the final `.m4b` as the primary transport while preserving chapter jumps, bookmarks, and resume through the same absolute timeline map.

**Tech Stack:** `dashboard/index.html` SPA, `monitor_server.py` library/catalog API, `epub_to_audiobook.py` pipeline, JSON manifest/status files, hls.js, ffmpeg/ffprobe, pytest/unittest.

---

## Verified current state

These facts were verified in the current codebase and run artifacts before writing this plan:

- The dashboard currently stores listening progress in book records with:
  - `listen_time_s`
  - `listen_chapter_index`
  - `listen_progress_hint`
  - `listen_src`
  - `listen_duration_s`
- Listening bookmarks currently store only:
  - `chapter_index`
  - `time_s`
  - `label`
- The current frontend source selector lives in `dashboard/index.html:2023-2045` as `mediaForChapter(run, preferredIndex, preferSrc)`.
- The current frontend progress saver lives in `dashboard/index.html:2049-2077` as `scheduleListenSave(...)` and stores chapter-relative time.
- The current backend patch handler lives in `monitor_server.py:1473-1612` and persists chapter-relative listening state/bookmarks.
- Run summaries already merge `manifest.json` into `status.json` in `monitor_server.py:985-1009`, including per-chapter `duration_s`, `m4a`, and `hls_playlist` when present.
- The generation pipeline writes per-chapter `wav`, `m4a`, and `duration_s` into `manifest.json` in `epub_to_audiobook.py:1550-1553`.
- The final `.m4b` file is already encoded with chapter metadata via ffmetadata in `epub_to_audiobook.py:973-1021`.
- `ffprobe -show_chapters` on the current `thinking-fast-and-slow.m4b` shows `chapter_count 50`, so chapter boundaries already exist in the final container.
- The current bug class was real: after completion, chapter playback could collapse onto the single full-book file without preserving chapter semantics.
- The current completed-run fix now prefers per-chapter final audio before run-level final audio, but it does **not** yet give the app one canonical progress model across generating and completed states.

## Product decisions locked by this plan

- The canonical user position is **absolute book time**, not chapter-local time.
- Chapter-relative time remains a derived field for transport/runtime convenience, not the source of truth.
- Bookmarks must survive the transition from live chapter playback to completed full-book playback without migration bugs.
- The app must support chapter taps and bookmark jumps whether playback is currently backed by HLS, per-chapter M4A, or final-book M4B.
- The UI should feel premium: fast resume, stable seek behavior, deterministic chapter jumps, and no “different rules before vs after completion.”
- Retain per-chapter artifacts at least until the canonical timeline flow is proven and tested. Do not optimize cleanup first.

## Non-goals for the first pass

- No multi-user sync.
- No cloud bookmark sync.
- No queue/multi-book playlist.
- No waveform rendering.
- No server-side transcoding redesign beyond timeline metadata needed for consistency.

---

## Canonical data model to implement

### Book-level listening progress

Add these persisted fields to each library book record:

- `listen_abs_time_s`: canonical absolute playback time from start of book
- `listen_chapter_time_s`: derived chapter-local playback time snapshot
- `listen_timeline_version`: integer schema version for future migration safety
- `listen_transport`: one of `hls`, `chapter_m4a`, `book_m4b`

Keep existing fields during migration, but make them derived/compatibility outputs:

- `listen_time_s` -> chapter-relative compatibility field
- `listen_chapter_index` -> current resolved chapter index
- `listen_progress_hint` -> display string
- `listen_duration_s` -> transport duration snapshot
- `listen_src` -> compatibility field, likely aliased from `listen_transport`

### Bookmark model

Each listening bookmark should persist:

- `abs_time_s` (canonical)
- `chapter_index` (snapshot for display)
- `chapter_time_s` (snapshot for display/fallback)
- `label`
- `created_at`
- optional: `timeline_version`

This prevents bookmark drift when the app changes transport modes.

### Run-level chapter map

Every run summary sent to the frontend should expose a canonical chapter timeline list with, per chapter:

- `index`
- `title`
- `duration_s`
- `start_s`
- `end_s`
- `status`
- `hls_url`
- `audio_m4a_url`
- `audio_url`

The frontend should not have to recompute offsets ad hoc from whichever file happens to be loaded.

---

## Implementation phases

### Phase 1: Expose canonical chapter offsets from backend

**Objective:** Make the backend return a stable absolute timeline map for every run.

**Files:**
- Modify: `monitor_server.py`
- Modify: `tests/test_monitor_server_phase2_api.py`

**Tasks:**
1. Add a helper in `monitor_server.py` that walks manifest/status chapters in order and computes cumulative `start_s` / `end_s` from `duration_s`.
2. Include those fields in `run_summary(...)` output.
3. Ensure missing `duration_s` is handled safely for in-progress chapters:
   - completed chapter with manifest duration -> compute exact offsets
   - currently running chapter without final duration -> omit exact end or mark provisional
4. Add API tests that assert the returned chapter map includes cumulative timing for completed chapters.
5. Add a test using a tiny synthetic manifest/status pair to prove offset math is stable and ordered.

**Verification commands:**
- `pytest tests/test_monitor_server_phase2_api.py -k chapter_timeline -v`
- `pytest tests/test_monitor_server_phase2_api.py -v`

### Phase 2: Introduce timeline resolution helpers in the frontend

**Objective:** Move the player from chapter-local thinking to canonical book-time thinking.

**Files:**
- Modify: `dashboard/index.html`
- Modify: `tests/test_dashboard_reader_and_settings_shell.py`

**Tasks:**
1. Add pure helpers in JS:
   - `chapterTimeline(run)`
   - `resolveAbsoluteToChapter(run, absTime)`
   - `resolveChapterToAbsolute(run, chapterIndex, chapterTime)`
2. Add tests that lock these helpers in place by asserting the exact function markers/strings in `dashboard/index.html`.
3. Refactor `mediaForChapter(...)` callers so they can accept a resolved target chapter derived from absolute time.
4. Keep transport selection separate from timeline resolution.

**Verification commands:**
- `pytest tests/test_dashboard_reader_and_settings_shell.py -k timeline -v`
- `pytest tests/test_dashboard_reader_and_settings_shell.py -v`

### Phase 3: Migrate persisted progress to canonical absolute time

**Objective:** Save and restore listening position in a way that survives transport changes.

**Files:**
- Modify: `monitor_server.py`
- Modify: `dashboard/index.html`
- Modify: `tests/test_monitor_server_phase2_api.py`

**Tasks:**
1. Extend `/api/library/patch` to accept and persist:
   - `listen_abs_time_s`
   - `listen_chapter_time_s`
   - `listen_transport`
   - `listen_timeline_version`
2. Preserve backward compatibility by continuing to accept current fields.
3. On reads, if `listen_abs_time_s` is missing but chapter-relative fields exist, derive absolute time from the returned chapter map.
4. Update `scheduleListenSave(...)` so it computes and saves both absolute and chapter-relative times.
5. Make the player restore from `listen_abs_time_s` first.

**Verification commands:**
- `pytest tests/test_monitor_server_phase2_api.py -k listen_abs -v`
- `pytest tests/test_monitor_server_phase2_api.py -v`

### Phase 4: Migrate listening bookmarks to absolute-time semantics

**Objective:** Make bookmarks transport-independent and stable across generation/completion.

**Files:**
- Modify: `monitor_server.py`
- Modify: `dashboard/index.html`
- Modify: `tests/test_monitor_server_phase2_api.py`

**Tasks:**
1. Extend `add_listening_bookmark` handling to accept `abs_time_s` and `chapter_time_s`.
2. Store canonical `abs_time_s` in bookmark records.
3. Update bookmark rendering to show both chapter label and human time from canonical resolution.
4. Add click-to-jump behavior for listening bookmarks based on `abs_time_s`.
5. Add a compatibility path so old bookmarks without `abs_time_s` still resolve via chapter-relative fields.

**Verification commands:**
- `pytest tests/test_monitor_server_phase2_api.py -k listening_bookmark -v`
- Browser smoke test: create bookmark on chapter playback, switch transport, re-open bookmark, verify same spoken position.

### Phase 5: Split playback transport policy from user timeline policy

**Objective:** Make the app behave consistently even when the underlying audio source changes.

**Files:**
- Modify: `dashboard/index.html`
- Optional later: `monitor_server.py`

**Locked transport policy:**
- While a chapter is still generating: prefer chapter HLS.
- When a chapter is complete but the whole book is not: prefer chapter M4A.
- When the whole book is complete: prefer final-book M4B for global scrubbing **if** chapter timeline metadata is available; otherwise fall back to chapter M4A.

**Tasks:**
1. Add a helper that selects transport independently from timeline state.
2. On completed books, allow the player to open the final `.m4b` and seek to `listen_abs_time_s`.
3. On chapter taps, compute chapter `start_s` and seek the M4B to that offset instead of replacing semantics with a raw file switch.
4. Preserve chapter list highlighting by deriving current chapter from absolute currentTime.
5. Keep chapter-M4A fallback for browsers/devices where M4B seeking behaves poorly.

**Verification commands:**
- Browser smoke test:
  - tap chapter 10 on completed book
  - verify player seeks to chapter 10 location
  - save progress
  - refresh page
  - verify same location restores

### Phase 6: Add migration-safe progress hint generation

**Objective:** Make displayed progress strings consistent and human-readable.

**Files:**
- Modify: `dashboard/index.html`
- Modify: `monitor_server.py` only if server-side hints are needed later

**Tasks:**
1. Generate hints from canonical resolution:
   - `Ch. 10 · Cognitive Ease · 03:21`
2. Fix chapter numbering to be user-facing 1-based consistently.
3. Make mini-player, detail page, and now-playing sheet all use the same formatter.
4. Ensure the active chapter outline follows the resolved chapter from absolute time.

### Phase 7: Add end-to-end regression coverage for the exact bug class

**Objective:** Prevent future regressions where completion changes the playback semantics.

**Files:**
- Modify: `tests/test_dashboard_reader_and_settings_shell.py`
- Modify: `tests/test_monitor_server_phase2_api.py`

**Regression cases to add:**
1. Completed-run chapter tap should not lose chapter identity.
2. Saving progress while on chapter-local transport then reopening on book-level transport should restore the same logical spot.
3. Saving a bookmark while generating and reopening it after completion should land in the same logical spot.
4. The frontend should prefer absolute timeline restoration over stale `listen_time_s` alone.

---

## Architecture notes for implementation

### Why absolute time is the right source of truth

- One full-book bar is the cleanest premium UX after completion.
- Bookmarks and resume need one stable coordinate system.
- Chapter taps become deterministic seeks instead of source swaps with fragile semantics.
- Transport can change without invalidating user data.

### Why chapter-relative fields should still exist

- HLS for a currently generating chapter only knows its own local transport timeline.
- Local chapter playback is still useful for fallback and mobile reliability.
- Snapshot fields make debugging and UI rendering easier.

### Why not rely on M4B chapter metadata alone

- Browser media controls do not expose audiobook chapter UX the way dedicated players do.
- The app still needs its own chapter list, active-highlight logic, bookmark resolution, and custom resume behavior.
- We already verified the M4B contains chapters, but the web app must surface them itself.

---

## Recommended execution order

1. Backend chapter offsets
2. Frontend timeline helpers
3. Progress migration to absolute time
4. Bookmark migration to absolute time
5. Completed-book transport policy using M4B + chapter seek
6. UI polish and regression suite

---

## Definition of done

This feature is done only when all of the following are true:

- You can bookmark a spot while the book is still generating.
- After the book finishes, that bookmark still lands on the same spoken moment.
- Tapping a chapter on a completed book jumps to the correct timestamp.
- Resume works across refresh/reopen regardless of whether the player uses HLS, chapter M4A, or book M4B underneath.
- The now-playing UI, mini-player, detail page, and bookmark list all agree on the active chapter and timestamp.
- Regression tests cover the generation-to-completion transition explicitly.

---

## Notes for future optimization

- Once the canonical timeline is stable, revisit whether chapter M4A retention is still needed long-term.
- If the final M4B proves reliable enough across target devices, completed-book playback can standardize on M4B while keeping chapter files only as fallback/download artifacts.
- If Android lock-screen integration matters more, add Media Session chapter skip actions after the timeline work lands.
