# Absolute Timeline Implementation Brief

Implement the remaining phases of the unified audiobook playback timeline work in `/home/philip/audiobook-generator`.

## Context

The backend chapter timeline offsets are already implemented in `monitor_server.py` via `annotate_chapter_timeline(...)` and covered by `tests/test_monitor_server_phase2_api.py::test_library_book_run_exposes_chapter_timeline_offsets`.

The remaining work is to make the app actually use canonical absolute book time, migrate listening bookmarks, and make completed-book playback use the final book transport with chapter seek mapping.

## Required outcomes

### 1) Frontend absolute-time helpers and persistence
Add pure JS helpers in `dashboard/index.html`:
- `chapterTimeline(run)`
- `resolveAbsoluteToChapter(run, absTime)`
- `resolveChapterToAbsolute(run, chapterIndex, chapterTime)`

Update playback save/restore behavior so the canonical persisted field is absolute book time.

Persist and prefer these fields:
- `listen_abs_time_s`
- `listen_chapter_time_s`
- `listen_transport`
- `listen_timeline_version`

Maintain backward compatibility with existing fields:
- `listen_time_s`
- `listen_chapter_index`
- `listen_progress_hint`
- `listen_src`
- `listen_duration_s`

### 2) Listening bookmarks absolute-time migration
Extend listening bookmarks to persist:
- `abs_time_s`
- `chapter_index`
- `chapter_time_s`
- `label`
- `created_at`
- optional timeline version if useful

Retain compatibility for old bookmarks that only have chapter-local fields.

### 3) Completed-book transport policy
For completed books, prefer the final run-level audio (`run.downloads.final_audio`) as the main transport when available, while preserving chapter seeking semantics through the canonical timeline.

That means:
- chapter taps should seek the final book to the tapped chapter `start_s`
- resume should seek from `listen_abs_time_s`
- bookmarks should jump by absolute time
- preserve fallback to chapter audio/HLS when needed

## File constraints
Primary files expected:
- `dashboard/index.html`
- `monitor_server.py`
- `tests/test_monitor_server_phase2_api.py`
- `tests/test_dashboard_reader_and_settings_shell.py`

## Verification targets
At minimum, run relevant tests and make them pass. Add focused regression tests for:
- timeline helper markers in dashboard
- new listen absolute-time fields in library patch API
- bookmark absolute-time persistence/compatibility
- completed-book transport behavior and restoration precedence where testable

Use the smallest safe change set. Preserve existing style and UI behavior except where needed for the new timeline model.

After edits, summarize:
- files changed
- what was implemented
- tests run and results
