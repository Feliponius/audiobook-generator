# Pipeline Chapter Resume — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** When the pipeline is restarted (after crash, kill, or server restart), detect which chapters are already complete and skip them, resuming from the first incomplete chapter instead of restarting from chapter 1.

**Architecture:** Before the main chapter loop in `process_book()`, scan the `chapters/` directory for existing chapter-level artifacts (concatenated `.wav`, `.m4a`, and complete chunk sets). Build a skip set and jump to the first chapter with missing chunks. The chunk-level resume (rewrite cache + WAV existence check at line 1479) already works — we just need the outer loop to skip completed chapters.

**Tech Stack:** Python 3.11, existing `epub_to_audiobook.py` codebase

---

## Background: What Already Works

The pipeline already has two resume mechanisms:

1. **Rewrite cache (line 1355–1368):** If a chunk's SHA-256 matches the cache in `rewrite-cache.json`, the rewritten text is reused without calling the LLM.

2. **Chunk WAV reuse (line 1479–1497):** If a `chunk-NNN.wav` file already exists and is non-empty, TTS synthesis is skipped and the chunk is counted as complete.

**What's missing:** The outer `for ch, chunks in chapter_batches:` loop (line 1301) always starts from index 0. Even chapters that are 100% done get re-iterated.

---

## Task 1: Add `detect_completed_chapters()` helper

**Objective:** Scan the run directory to determine which chapters are fully complete and should be skipped on restart.

**Files:**
- Modify: `epub_to_audiobook.py` — add function after `cleanup_intermediate_audio_files()` (around line 1101)

**Step 1: Write failing test**

```python
# tests/test_chapter_resume.py
from pathlib import Path

def test_detect_completed_chapters_from_disk():
    """Chapters with all chunk WAVs + chapter WAV + M4A are marked complete."""
    from epub_to_audiobook import detect_completed_chapters
    
    with TemporaryDirectory() as td:
        root = Path(td)
        # Simulate chapter 1: 3 chunks, all WAVs present + chapter.wav + chapter.m4a
        ch1 = root / "chapters" / "001-cover-page"
        ch1.mkdir(parents=True)
        for i in range(1, 4):
            (ch1 / f"chunk-{i:03d}.wav").write_text("fake wav")
        (root / "chapters" / "001-cover-page.wav").write_text("fake")
        (root / "chapters" / "001-cover-page.m4a").write_text("fake")
        
        # Simulate chapter 2: 3 chunks, only 1 WAV (incomplete)
        ch2 = root / "chapters" / "002-title-page"
        ch2.mkdir(parents=True)
        (ch2 / "chunk-001.wav").write_text("fake")
        
        result = detect_completed_chapters(root, total_chunks_map={1: 3, 2: 3})
        
        assert result == {1}, f"Expected {{1}}, got {result}"
```

**Step 2: Run to verify failure**

```bash
cd /home/philip/audiobook-generator
venv/bin/python -m pytest tests/test_chapter_resume.py::test_detect_completed_chapters_from_disk -v
```
Expected: FAIL — `detect_completed_chapters` not defined

**Step 3: Implement `detect_completed_chapters()`**

```python
def detect_completed_chapters(
    book_dir: Path,
    total_chunks_map: dict[int, int],
) -> set[int]:
    """Return set of chapter indices that are fully complete.
    
    A chapter is complete when:
    1. All expected chunk WAV files exist and are non-empty
    2. The concatenated chapter WAV exists
    3. The chapter M4A exists (or HLS playlist for hls-tts mode)
    """
    chapters_dir = book_dir / "chapters"
    if not chapters_dir.is_dir():
        return set()
    
    completed: set[int] = set()
    for ch_dir in sorted(chapters_dir.iterdir()):
        if not ch_dir.is_dir():
            continue
        # Parse chapter index from directory name like "001-cover-page"
        try:
            idx = int(ch_dir.name.split("-", 1)[0])
        except (ValueError, IndexError):
            continue
        
        expected = total_chunks_map.get(idx)
        if expected is None:
            continue
        
        # Count existing non-empty WAV chunks
        existing = 0
        for i in range(1, expected + 1):
            wav = ch_dir / f"chunk-{i:03d}.wav"
            if wav.exists() and wav.stat().st_size > 0:
                existing += 1
        
        if existing < expected:
            continue
        
        # Check chapter-level artifacts
        chapter_wav = chapters_dir / f"{ch_dir.name}.wav"
        chapter_m4a = chapters_dir / f"{ch_dir.name}.m4a"
        chapter_hls = ch_dir / f"chapter-{idx:03d}.m3u8"
        
        if (chapter_wav.exists() and chapter_wav.stat().st_size > 0) or \
           (chapter_m4a.exists() and chapter_m4a.stat().st_size > 0) or \
           (chapter_hls.exists() and chapter_hls.stat().st_size > 0):
            completed.add(idx)
    
    return completed
```

**Step 4: Run tests to verify pass**

```bash
cd /home/philip/audiobook-generator
venv/bin/python -m pytest tests/test_chapter_resume.py::test_detect_completed_chapters_from_disk -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add epub_to_audiobook.py tests/test_chapter_resume.py
git commit -m "feat: add detect_completed_chapters() helper for pipeline resume"
```

---

## Task 2: Handle stale chapter directories from prior runs

**Objective:** Add a test for the edge case where previous runs left partial directories (like the `001-benn-*` vs `001-cover-page` situation).

**Files:**
- Modify: `tests/test_chapter_resume.py`

**Step 1: Write test**

```python
def test_detect_completed_ignores_stale_duplicate_dirs():
    """Old Benn-named directories from prior runs don't confuse detection."""
    from epub_to_audiobook import detect_completed_chapters
    
    with TemporaryDirectory() as td:
        root = Path(td)
        # Old run dir (Benn name, fully complete)
        old = root / "chapters" / "001-benn-9781595550552-epub-c1-r1"
        old.mkdir(parents=True)
        for i in range(1, 4):
            (old / f"chunk-{i:03d}.wav").write_text("fake")
        (root / "chapters" / "001-benn-9781595550552-epub-c1-r1.wav").write_text("fake")
        (root / "chapters" / "001-benn-9781595550552-epub-c1-r1.m4a").write_text("fake")
        
        # New run dir (clean name, only 1 of 3 chunks done)
        new = root / "chapters" / "001-cover-page"
        new.mkdir(parents=True)
        (new / "chunk-001.wav").write_text("fake")
        
        # total_chunks_map uses the current chapter indices (all chapters)
        result = detect_completed_chapters(root, total_chunks_map={1: 3, 2: 5})
        
        # Nothing should be "complete" because the clean-named dir isn't done
        # and the old Benn dir isn't the current chapter slug
        assert result == set(), f"Expected empty set, got {result}"
```

**Step 2: Run test**

```bash
venv/bin/python -m pytest tests/test_chapter_resume.py::test_detect_completed_ignores_stale_duplicate_dirs -v
```
Expected: FAIL — the old directory with 3 complete WAVs would make it look like chapter 1 is complete

**Step 3: Fix the implementation**

The `detect_completed_chapters` function needs to match against the **current** chapter slugs from the new run, not just any directory with a matching index prefix. Pass in the expected slug map:

```python
def detect_completed_chapters(
    book_dir: Path,
    total_chunks_map: dict[int, int],
    chapter_slugs: dict[int, str],  # NEW: {1: "001-cover-page", 2: "002-title-page", ...}
) -> set[int]:
    chapters_dir = book_dir / "chapters"
    if not chapters_dir.is_dir():
        return set()
    
    completed: set[int] = set()
    for idx, slug in chapter_slugs.items():
        expected = total_chunks_map.get(idx)
        if expected is None:
            continue
        ch_dir = chapters_dir / slug
        if not ch_dir.is_dir():
            continue
        
        existing = 0
        for i in range(1, expected + 1):
            wav = ch_dir / f"chunk-{i:03d}.wav"
            if wav.exists() and wav.stat().st_size > 0:
                existing += 1
        if existing < expected:
            continue
        
        chapter_wav = chapters_dir / f"{slug}.wav"
        chapter_m4a = chapters_dir / f"{slug}.m4a"
        chapter_hls = ch_dir / f"chapter-{idx:03d}.m3u8"
        
        if (chapter_wav.exists() and chapter_wav.stat().st_size > 0) or \
           (chapter_m4a.exists() and chapter_m4a.stat().st_size > 0) or \
           (chapter_hls.exists() and chapter_hls.stat().st_size > 0):
            completed.add(idx)
    
    return completed
```

**Step 4: Run tests**

```bash
venv/bin/python -m pytest tests/test_chapter_resume.py -v
```
Expected: both tests PASS

**Step 5: Commit**

```bash
git add epub_to_audiobook.py tests/test_chapter_resume.py
git commit -m "fix: detect_completed_chapters matches against current chapter slugs only"
```

---

## Task 3: Wire resume into `process_book()` main loop

**Objective:** Call `detect_completed_chapters()` before the chapter loop and skip completed chapters.

**Files:**
- Modify: `epub_to_audiobook.py` — `process_book()` function

**Step 1: Write integration test**

```python
def test_process_book_resumes_from_first_incomplete_chapter():
    """When chapters 1-3 are complete, the pipeline starts at chapter 4."""
    # This test is best done as an integration test with a real (tiny) EPUB
    # We'll verify via status.json after a simulated restart
    pass  # Integration test — write after implementation is verified manually
```

**Step 2: Add resume logic to `process_book()`**

After `status_by_chapter = {entry["index"]: entry for entry in status["chapters"]}` (line 1241), add:

```python
    # --- RESUME LOGIC ---
    # Build maps for detection
    chapter_slugs = {
        ch.index: f"{ch.index:03d}-{slugify(ch.title)}"
        for ch, _ in chapter_batches
    }
    total_chunks_map = {
        ch.index: len(chunks)
        for ch, chunks in chapter_batches
    }
    completed_chapters = detect_completed_chapters(book_dir, total_chunks_map, chapter_slugs)
    
    resumed_from = None
    if completed_chapters:
        resumed_from = min(idx for idx, _ in chapter_batches if idx not in completed_chapters)
        for idx in sorted(completed_chapters):
            entry = status_by_chapter.get(idx)
            if entry:
                entry["status"] = "completed"
                # Try to recover stats from manifest if available
                for mch in manifest.get("chapters", []):
                    if mch.get("index") == idx:
                        entry["rewrite_completed_chunks"] = len(mch.get("stats", {}).get("chunks", []))
                        entry["tts_completed_chunks"] = len(mch.get("stats", {}).get("chunks", []))
                        entry["hls_playlist"] = mch.get("hls_playlist")
                        break
            status["progress"]["completed_chapters"] = len(completed_chapters)
        status["resumed_from_chapter"] = resumed_from
        status["previously_completed_chapters"] = sorted(completed_chapters)
        log(f"⏭️ Resuming: {len(completed_chapters)} chapters already complete, starting from chapter {resumed_from}")
        save_status()
        emit_event("pipeline_resumed", 
                   completed_chapters=sorted(completed_chapters),
                   starting_from=resumed_from)
```

Then modify the chapter loop (line 1301):

```python
    for ch, chunks in chapter_batches:
        if completed_chapters and ch.index in completed_chapters:
            log(f"⏭️ Skipping completed chapter {ch.index}: {ch.title}")
            chapter_wall_start = time.perf_counter()
            chapter_slug = f"{ch.index:03d}-{slugify(ch.title)}"
            chapter_status = status_by_chapter[ch.index]
            chapter_status["status"] = "completed"
            # Try to recover chapter WAV path for final concat
            chapter_wav = chapter_dir / f"{chapter_slug}.wav"
            if chapter_wav.exists() and chapter_wav.stat().st_size > 0:
                ch.wav_path = chapter_wav
                chapter_wavs.append(chapter_wav)
                ch.duration_s = wav_duration_seconds(chapter_wav)
            continue
        
        # ... existing chapter processing code ...
```

**Step 3: Handle edge case — all chapters complete**

```python
    if len(completed_chapters) == len(chapter_batches):
        log("✅ All chapters already complete — skipping to encoding")
        # All chapter WAVs should already be on disk; collect them
        for ch, _ in chapter_batches:
            chapter_slug = f"{ch.index:03d}-{slugify(ch.title)}"
            chapter_wav = chapter_dir / f"{chapter_slug}.wav"
            if chapter_wav.exists():
                ch.wav_path = chapter_wav
                chapter_wavs.append(chapter_wav)
        # Fall through to encoding below
```

**Step 4: Run all existing tests to confirm no regressions**

```bash
cd /home/philip/audiobook-generator
venv/bin/python -m pytest tests/ -v
```
Expected: all existing tests pass, new resume tests pass

**Step 5: Commit**

```bash
git add epub_to_audiobook.py tests/
git commit -m "feat: chapter-level resume — skip completed chapters on restart"
```

---

## Task 4: Dashboard awareness of resume state

**Objective:** Show in the dashboard that the pipeline resumed rather than started fresh, and which chapters were already done.

**Files:**
- Modify: `dashboard/index.html` — chapter list rendering
- Modify: `monitor_server.py` — `run_summary()` (already handles chapters)

**Step 1: Add resume indicator to dashboard**

In the book detail page, when `run.resumed_from_chapter` is present, show a notice above the chapter list:

```javascript
// In renderChapterList() or equivalent
if (run.resumed_from_chapter != null) {
    const notice = document.createElement('div');
    notice.className = 'resume-notice';
    notice.innerHTML = `⏭️ Resumed from chapter ${run.resumed_from_chapter} — ${run.previously_completed_chapters?.length || 0} chapters were already complete`;
    container.prepend(notice);
}
```

**Step 2: Mark skipped chapters visually**

For chapters in `run.previously_completed_chapters`, show them as completed immediately:

```javascript
const wasPreCompleted = run.previously_completed_chapters?.includes(ch.index);
if (ch.status === 'completed' || wasPreCompleted) {
    statusEl.className = 'toc-status done';
    statusEl.textContent = '✓';
}
```

**Step 3: Commit**

```bash
git add dashboard/index.html
git commit -m "feat: show resume state in dashboard chapter list"
```

---

## Task 5: Manual smoke test on America book

**Objective:** Verify resume works end-to-end on the real America book run.

**Steps:**

1. Let the current run reach chapter 8+ (where previous WAVs exist)
2. Kill the pipeline: `kill $(pgrep -f epub_to_audiobook)`
3. Restart from the dashboard
4. Verify in the dashboard: chapters 1-6 should show as completed immediately, progress jumps ahead
5. Verify logs show `⏭️ Resuming: N chapters already complete`
6. Verify the pipeline reaches chapter 7+ quickly (WAV reuse)

```bash
# Watch the logs during restart
tail -f /home/philip/audiobook-generator/library/runs/2842a570-*/america-the-last-best-hope-volume-i/events.jsonl
```

---

## Edge Cases & Pitfalls

1. **Slug mismatch from TOC title change:** Old runs used Benn filenames as slugs. The `chapter_slugs` map uses the current run's slugs (clean titles). Old Benn directories are ignored — only the current slug's directory is checked.

2. **Partial chapter with some WAVs:** If a chapter has 50/100 WAVs, it's NOT marked complete. The chunk-level resume (line 1479) handles skipping those 50 WAVs individually.

3. **Config change between runs:** If `max_chars` or `rewrite_policy` changes, the rewrite cache is invalidated (line 1330-1342). Chunk WAVs would still be reused, but rewritten text would be regenerated. This is correct behavior.

4. **HLS mode:** For `hls-tts` mode, the chapter is considered complete if the HLS playlist (`chapter-NNN.m3u8`) exists.

5. **First-ever run:** `detect_completed_chapters()` returns empty set. The loop runs normally. Zero overhead.

6. **`chapter_wavs` list for final encoding:** When skipping completed chapters, we need to collect their WAV paths so the final M4B concat still works. The `chapter_wav` path is reconstructed from the slug.

---

## What This Doesn't Do

- **Does NOT handle mid-chapter resume within the *current* chapter differently.** The existing chunk-level WAV check already handles this — partially completed chapters resume from the first missing chunk.
- **Does NOT preserve in-flight Kokoro worker state.** Workers are re-spawned on restart. This is fine since WAVs are the durable checkpoint.
- **Does NOT auto-restart on crash.** The user must click "Start" again from the dashboard. A future enhancement could add auto-retry in the monitor server.
