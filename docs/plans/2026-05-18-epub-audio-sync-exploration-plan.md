# EPUB-to-Audio Sync Exploration Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Define and prototype a future feature set for starting audiobook playback from a location inside the EPUB reader and, later, following audio playback with text highlighting.

**Architecture:** Treat EPUB reading locations and audiobook playback locations as two coordinate systems joined by a mapping layer. Use EPUB CFIs / reader selections on one side and the canonical absolute audiobook timeline on the other. Ship this in stages: first approximate paragraph/chunk-based seeking, then optional coarse follow-along highlighting, and only later sentence/word-accurate sync if the product value justifies alignment work.

**Tech Stack:** `dashboard/index.html` SPA, epub.js reader, `monitor_server.py` library API, `epub_to_audiobook.py` pipeline, JSON status/manifest artifacts, existing chapter timeline metadata.

---

## Verified current state

These facts were verified in the current codebase before writing this plan:

- The reader already loads EPUBs with `epub.js` in `dashboard/index.html`.
- Reading position is already persisted via `read_cfi` / `read_progress_hint` and restored with `rendition.display(...)`.
- The audiobook pipeline extracts chapters from the EPUB in spine order in `epub_to_audiobook.py:608-662`.
- The pipeline chunks chapter text deterministically in `epub_to_audiobook.py:714-724`.
- Rewritten chunk text is already written to per-chapter `chunk-XXX.txt` files in `epub_to_audiobook.py:1333-1352`.
- Chapter progress metadata already exists, and the playback architecture now has a canonical chapter timeline plan based on absolute book time.
- No exact sentence/word timing or alignment metadata is currently persisted by the pipeline.
- The current system therefore supports a plausible approximate/chunk-based mapping design, but not exact karaoke-style synchronization yet.

## Product scope decisions for this exploration

- **In scope now:** write down the design and revisit later.
- **First implementation target when resumed:** “Listen from here” from EPUB location.
- **Second implementation target:** coarse follow-along highlighting using chunk-level or paragraph-level approximations.
- **Deferred unless clearly worth it:** sentence-level or word-level exact sync.

## Feature levels

### Level 1: Approximate “Listen from here”

User flow:
- User opens EPUB reader.
- User taps or long-presses a paragraph / current location.
- App offers **Listen from here**.
- App estimates the matching audiobook timestamp and seeks there.

Expected quality:
- Good enough to start near the chosen passage.
- Not expected to land on the exact spoken word.

### Level 2: Chunk-aware “Listen from here”

User flow stays the same, but mapping uses deterministic chapter/chunk metadata instead of raw proportional estimation.

Expected quality:
- Better than simple proportional chapter seeking.
- Likely accurate to the nearest chunk or nearby intra-chunk position.

### Level 3: Follow-along highlighting

User flow:
- User is listening while viewing the EPUB.
- Reader highlights the current chunk / paragraph / sentence.

Expected quality options:
- coarse: current paragraph or chunk region
- medium: estimated sentence
- premium: exact sentence/word timing

---

## Main technical problem to solve

The hard problem is **not** detecting where in the EPUB the user tapped.

The hard problem is mapping:
- EPUB location / selection / paragraph
- to chapter-relative text position
- to canonical audiobook absolute time

This needs an explicit bridge layer between the reader and the playback timeline.

---

## Proposed architecture when resumed

### Layer 1: Reader location capture

Capture one of these as the user intent source:
- current visible `read_cfi`
- selected paragraph / text fragment
- chapter-local EPUB location

Preferred first-pass choices:
1. current visible location
2. paragraph tap / paragraph action

Avoid first-pass freeform text selection matching if a simpler paragraph-based interaction is sufficient.

### Layer 2: Text anchor normalization

Convert reader intent into a stable content anchor such as:
- chapter index
- paragraph index within chapter
- normalized paragraph text hash
- optional character offset within paragraph

This layer should exist so the feature does not depend entirely on fragile raw CFI comparisons.

### Layer 3: Audio mapping

Map the content anchor to the canonical audio timeline using one of these strategies:

#### Strategy A: Chapter-proportional estimate
- find chapter
- estimate paragraph position within chapter text length
- multiply by chapter duration
- convert to `absolute_time_s`

Pros:
- easiest possible version

Cons:
- rough accuracy only

#### Strategy B: Chunk-aware estimate
- persist chunk text metadata and chunk durations
- map paragraph to nearest chunk by text containment / offsets
- seek to chunk start or estimated intra-chunk offset

Pros:
- much better cost/benefit
- fits current deterministic chunk pipeline

Cons:
- still not exact enough for word-following

#### Strategy C: Forced alignment / timing metadata
- produce sentence or word timestamps after TTS
- persist alignment data in artifacts/API
- use that for exact seek/highlighting

Pros:
- best user experience

Cons:
- materially larger project
- likely needs new tooling and storage design

### Layer 4: Playback integration

Once the mapping returns `absolute_time_s`, reuse the canonical audiobook timeline architecture:
- resolve chapter from absolute time
- choose transport (`hls`, chapter audio, or final `m4b`)
- seek and play

This keeps EPUB-to-audio sync as a feature on top of the playback architecture instead of a competing playback model.

---

## Recommended implementation phases for later

### Phase 1: Add metadata needed for chunk-aware mapping

**Objective:** Make approximate text-to-audio seeking possible without full alignment.

**Files:**
- Modify: `epub_to_audiobook.py`
- Modify: `monitor_server.py`
- Modify: relevant API tests

**Tasks:**
1. Persist per-chunk rewritten text metadata in a machine-readable summary artifact.
2. Persist per-chunk durations and cumulative chapter-local offsets.
3. Expose chunk timeline metadata through run summaries / API.
4. Verify that chunk ordering remains deterministic across reruns.

### Phase 2: Add reader-side “Listen from here” intent capture

**Objective:** Let the EPUB reader express a location to convert into audio playback.

**Files:**
- Modify: `dashboard/index.html`
- Modify: reader shell tests

**Tasks:**
1. Add UI affordance for current location and/or paragraph action.
2. Capture current CFI and visible chapter context.
3. Translate reader intent into a normalized content anchor.
4. Feed the anchor into a mapping helper instead of seeking directly.

### Phase 3: Implement chunk-aware seek mapping

**Objective:** Convert reader anchors into audio seeks with usable accuracy.

**Files:**
- Modify: `dashboard/index.html`
- Optional helper module if frontend logic grows
- Modify: tests for mapping helpers

**Tasks:**
1. Add pure helpers for paragraph/chunk matching.
2. Resolve anchor -> chapter chunk -> `absolute_time_s`.
3. Reuse canonical playback helpers to choose transport and seek.
4. Show fallback messaging if exact mapping is unavailable.

### Phase 4: Add coarse follow-along highlighting

**Objective:** Let the EPUB reader roughly track the currently spoken region.

**Files:**
- Modify: `dashboard/index.html`
- Modify: reader styling/test coverage

**Tasks:**
1. Map current playback `absolute_time_s` back to chapter/chunk.
2. Locate the matching reader content region.
3. Highlight current paragraph/chunk in epub.js.
4. Ensure highlights update cheaply and do not fight manual paging.

### Phase 5: Evaluate premium alignment path

**Objective:** Decide whether exact sentence/word sync is worth the cost.

**Files:**
- likely new pipeline tooling and metadata format
- likely new tests and storage artifacts

**Research questions:**
1. What alignment tooling works reliably with Kokoro output?
2. Can rewritten chunk text be aligned robustly post-TTS?
3. What metadata size overhead would sentence/word timing introduce?
4. Is exact highlighting worth the complexity versus chunk-level UX?

---

## Risks and pitfalls

### Pitfall: using only raw EPUB CFI as the audio mapping key
CFIs are useful for restore/navigation, but alone they are a poor audio mapping coordinate.

**Mitigation:** convert to normalized chapter/paragraph/text anchors before matching.

### Pitfall: trying to solve word-perfect sync first
That would delay useful value and add major complexity too early.

**Mitigation:** ship approximate/chunk-aware seek first.

### Pitfall: coupling this feature to one transport type
If mapping targets chapter-local files only, it will break once transport changes.

**Mitigation:** always target canonical `absolute_time_s`, then resolve transport afterward.

### Pitfall: highlight logic fighting the reader UX
Aggressive auto-scroll/highlight can make reading feel broken.

**Mitigation:** start with lightweight highlighting and add a clear opt-in follow mode if needed.

---

## Recommended next time this is resumed

Resume in this order:
1. finish the core absolute-time playback migration already in progress
2. add chunk metadata required for text-to-audio mapping
3. prototype **Listen from here** before any highlighting work
4. only then decide whether coarse or premium highlighting is worth building

---

## Definition of done for future Phase 1

The first version of this feature should be considered successful when:
- a user can choose **Listen from here** from the EPUB reader
- playback starts near the intended passage
- it works both during generation and after completion
- the feature relies on canonical absolute time, not transport-specific local offsets
- tests cover the mapping helpers and fallback behavior

---

## Decision note

For now, this is intentionally a **saved exploration plan**, not an active implementation commitment. The likely best product path is:
- build **Listen from here** first
- revisit highlighting later
- defer exact sentence/word sync until the simpler version proves valuable
