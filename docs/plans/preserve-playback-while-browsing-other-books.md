# Preserve active playback while browsing other book detail pages

## Problem
When one book is currently playing, simply navigating to another book's detail page stops playback from the first book. Philip expects playback to continue unless he explicitly chooses to switch books (for example by pressing Play audiobook / Continue listening on the other book, or deleting/stopping the currently playing book).

## Root-cause evidence
In `dashboard/index.html`, `openBookDetail(id, opts)` currently contains an unconditional stop for any book-detail navigation to a different book:

```js
if (state.playerSession && state.playerSession.id !== id) stopPlayer();
```

That means route changes like `#/book/<other-id>` kill the active player just from browsing.

Also, later in the same function, when `keepMedia` is false it may call `attachPlayerMedia(id, b, run, m)` for the viewed book, which means passive browsing can hijack the current player state instead of requiring an explicit user action.

## Expected behavior
- If book A is playing and the user opens book B's detail page just to inspect it, playback for A should continue.
- Mini-player / Now Playing / reader dock should keep representing the actually playing book.
- Book B detail page can still show its own metadata, progress, controls, etc., but should not automatically stop or replace book A playback just because the route changed.
- Playback should switch only on explicit intent, such as:
  - pressing Play audiobook on book B
  - pressing Continue listening for book B when that should activate B
  - deleting/stopping the currently playing book

## Constraints
- Use Cursor Composer 2.5 regular (`--model composer-2.5`), not a fast model.
- Make the smallest focused change.
- Preserve existing player architecture and mini-player behavior.
- Do not regress the recent custom audio sheet work.
- Do not break explicit switching to another book when user presses Play audiobook.

## Likely approach
Introduce logic in `openBookDetail()` to distinguish:
1. passive browsing of another book while a different book is already playing
2. explicit activation of playback for the viewed book

Passive browsing should preserve the active player and not overwrite player metadata with the browsed book.

## Verification
Please add/update a focused regression test in `tests/test_dashboard_reader_and_settings_shell.py` that captures the intended behavior at the source level.

Then verify with:
```bash
python3 -m unittest tests.test_dashboard_reader_and_settings_shell -v
```

Please summarize:
- exact logic change
- changed files
- how explicit book switching still works
