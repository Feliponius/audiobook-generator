# Audiobook Library Runtime/Reader Fix Plan

> **For Hermes:** Use Cursor Composer 2 as the sole code-change executor for this plan, then verify independently.

**Goal:** Make library conversions fully LLM-free by default, show trustworthy generation state/evidence instead of stale "GENERATING", and add real reader navigation controls.

**Architecture:** Keep the existing Python server + single-file dashboard architecture. Fix the server-side conversion defaults and status inference first, then expose clearer diagnostics in the dashboard and add lightweight epub.js reader controls without changing the core storage model.

**Tech Stack:** Python `http.server`, `epub_to_audiobook.py`, vanilla HTML/CSS/JS dashboard, epub.js, Kokoro TTS.

---

## Confirmed current findings

1. `monitor_server.py` currently hard-forces `rewrite_policy` to `selective` in settings/default merge paths.
2. `/api/settings` currently serves `rewrite_policy: "selective"`.
3. `/api/library/start` currently hard-codes `rewrite_policy = "selective"` before spawning `epub_to_audiobook.py`.
4. The stalled run at `library/runs/1123554b-99dd-4582-bc6c-ad9b267fb218/thinking-fast-and-slow` has:
   - `rewrite_policy: "full"`
   - `llm_rewrite_chunks: 1`
   - no active `epub_to_audiobook.py` process
   - stale `status.json`/`events.jsonl` timestamps from 2026-05-17 15:45:41 CDT
5. `infer_book_conversion_status()` reports `running` whenever a run exists without `error` or `output`, even if the process is dead/stale.
6. The reader UI has only back/bookmark/title controls. No prev/next/TOC controls are exposed.

---

## Task 1: Make conversion defaults LLM-free

**Objective:** Ensure new audiobook runs use deterministic cleanup only, 2 Kokoro workers, and no rewrite model.

**Files:**
- Modify: `monitor_server.py`
- Verify: `/api/settings`, `/api/library/start`, generated `status.json`

**Steps:**
1. Change default app settings so the persisted/default `rewrite_policy` is `script-only`.
2. Change `read_app_settings()` and `merge_app_settings()` so they preserve/serve `script-only` rather than forcing `selective`.
3. Change `/api/library/start` so it passes `--rewrite-policy script-only`.
4. Ensure the start command continues to force `--tts-engine kokoro`, `--kokoro-workers 2`, and does not wire any LLM backend for library conversions.
5. Update any misleading UI copy in settings that still promises “fast selective rewrite”.

**Verification:**
- `GET /api/settings` returns `rewrite_policy: "script-only"`.
- Starting a new run creates `status.json` with `rewrite_policy: "script-only"`.
- Early chapter stats show `scripted_cleanup_chunks > 0` and `llm_rewrite_chunks == 0`.

---

## Task 2: Make generation state trustworthy

**Objective:** Stop showing stale dead runs as active generation and surface concrete evidence when work is actually happening.

**Files:**
- Modify: `monitor_server.py`
- Modify: `dashboard/index.html`

**Steps:**
1. Add run liveness detection on the server side. Prefer checking for a matching active `epub_to_audiobook.py` process and/or a recent status/event file update window.
2. Extend `infer_book_conversion_status()` so stale/dead runs are not shown as `running` forever. Use a distinct state like `stalled` or map to `error` with a visible message.
3. Include additional run summary fields such as:
   - `updated_at`
   - `current` chapter/chunk
   - last event summary
   - `is_live` / `stale` indicator
4. Promote the most useful diagnostics into the visible book detail view instead of hiding all meaningful evidence inside collapsed diagnostics.
5. Make the CTA/status area say the truth, e.g. `Generating`, `Stalled`, `Ready`, `Not started`.

**Verification:**
- A dead stale run no longer appears as fresh active generation.
- A live run shows recent event/update evidence in the detail view.
- The library card/detail status matches actual process state.

---

## Task 3: Add actual reader navigation controls

**Objective:** Make the e-reader usable for navigation, not just rendering.

**Files:**
- Modify: `dashboard/index.html`

**Steps:**
1. Add visible controls in the reader chrome for:
   - previous page
   - next page
   - table of contents / chapter jump
   - current progress text
2. Wire previous/next to `state.rendition.prev()` / `state.rendition.next()`.
3. Load epub navigation from epub.js and render a simple TOC list or picker.
4. Keep current save behavior for `read_cfi` and `read_progress_hint` on relocation.
5. Ensure controls work on mobile layout.

**Verification:**
- Reader view shows visible nav controls.
- Prev/next changes pages.
- TOC opens and jumps to the selected section.
- Progress text updates when relocating.

---

## Task 4: Handle existing stuck runs safely

**Objective:** Make sure previously stuck runs do not permanently poison the UX.

**Files:**
- Modify: `monitor_server.py`
- Optional: `dashboard/index.html`

**Steps:**
1. Decide how stale runs should be represented for existing books.
2. Preserve historical run data, but let the user restart conversion if the run is stale/dead.
3. Ensure `/api/library/start` allows restart when the previous run is stale rather than falsely blocking on `already in progress`.

**Verification:**
- The currently stuck Thinking, Fast and Slow library run is no longer treated as active if no process exists.
- The user can restart conversion from the UI once status is corrected.

---

## Independent verification checklist

1. Restart the local server.
2. `GET /api/settings` and confirm `script-only` + `kokoro_workers: 2`.
3. Start a fresh conversion for a test book.
4. Confirm there is an active `epub_to_audiobook.py` process while generating.
5. Read the new run’s `status.json` and `events.jsonl`.
6. Confirm no `llm_used: true` events occur.
7. Open the book detail page and confirm visible progress evidence.
8. Open reader mode and confirm prev/next/TOC controls work.

---

## Notes for Cursor prompt

Require a minimal, focused fix. Do not refactor unrelated code. Preserve the current single-file dashboard pattern unless a tiny helper extraction is clearly necessary. After editing, summarize changed files and why.