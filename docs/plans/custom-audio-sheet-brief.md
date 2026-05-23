# Custom audio-first expanded player fix

## Problem
The expanded audiobook player currently exposes a raw `<video id="hlsVideo">` element inside the sheet. For audio-only `.m4b` playback on Android/Chrome, this renders as a large black video rectangle with native controls, which looks broken and does not match the intended audiobook UX.

## Intended UX reference
Use the design direction from `sketches/full-app/index.html` around the Now Playing section (roughly lines 927-950):
- cover art / title / author / chapter info
- seek slider with elapsed + remaining/duration labels
- transport row with back 15s, previous, play/pause, next, forward 30s
- audio-first custom controls
- action row including Book details

The hidden media element should keep powering playback in the background, but the visible expanded sheet should be custom UI, not native browser media chrome.

## Current implementation notes
- Main live file: `dashboard/index.html`
- Expanded sheet markup is around lines 1321-1337
- The sheet currently contains `<video id="hlsVideo" playsinline controls ...>`
- CSS around lines 740-833 styles the visible video block
- Existing player state / plumbing lives around lines 1424-1655 and 1965+
- Background/mini-player behavior already depends on the same media element, so preserve that architecture

## Requirements
1. Keep a single hidden media element for playback continuity and background behavior.
2. Remove the visible raw native media box from the expanded sheet.
3. Build custom controls in the expanded sheet for audiobook playback.
4. Match the sketch direction reasonably closely for mobile-first UX.
5. Preserve existing playback/resume/progress save behavior.
6. Preserve existing mini-player and reader dock behavior.
7. Keep chapter numbering semantics correct (run.chapters[].index is already 1-based).
8. Make minimal, focused changes; do not refactor unrelated dashboard areas.

## Minimum control set for the sheet
- cover art / placeholder
- title / author / current chapter/progress hint
- seek range input bound to current playback time
- elapsed time label
- remaining or total duration label
- skip back 15s
- previous chapter (or previous playable unit)
- play/pause
- next chapter
- skip forward 30s
- Book details button

If there is an easy, low-risk way to add playback speed without disturbing existing behavior, that is okay, but it is optional. Prioritize solid custom transport UI first.

## Technical constraints
- Use Cursor as code executor; keep changes focused in `dashboard/index.html` unless a test file needs a small update.
- Hidden media element can remain `<video>` or become `<audio>` if safe, but the visible UI must be custom and audio-first.
- Avoid breaking HLS support if it is still needed elsewhere.
- Do not rely on the native browser controls for the expanded sheet.

## Verification target
After editing:
- run the relevant unit tests
- add/update a focused regression test if appropriate for the new markup/controls
- summarize changed areas and verification performed
