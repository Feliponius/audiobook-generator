# Full app sketch

Interactive front-to-back mockup with **theme switching** and a **placeholder persistent player**.

## Open

From repo root:

```bash
# optional local server
python3 -m http.server 8765 --directory sketches/full-app
```

Then visit `http://127.0.0.1:8765/` — or open `index.html` directly in a browser.

## Themes

| Mode | Palette | Toggle |
|------|---------|--------|
| **Dark · Forest** | Green / spruce / emerald accents | Default |
| **Light · Play Books** | Blue / mist / white surfaces | Settings or header buttons |

Choice is saved in `localStorage` (`sketch-theme`).

## Navigation model

- **Bottom tabs** are the only primary nav: Library · Now playing · Settings
- **Tab root screens** have no duplicate top chips (no “Library” label + settings cog when the tab bar already covers that)
- **Stack screens** (book, reader) use a minimal bar: back arrow only (+ optional utility: ⋯ or Aa)
- **Now playing** has no top bar; “Book details” is a secondary action in the control row, not a competing nav label

## Flow

1. **Library** — continue hero, upload zone, book grid → tap book for detail
2. **Book detail** — hero, continue card, chapters, collapsed notes/technical (push, no tab)
3. **Reader** — content pane + reader dock (placeholder player)
4. **Now playing** tab — full transport UI
5. **Settings** — theme toggle, voice, advanced collapsed

## Placeholder player

- **Mini bar** — above bottom nav on Library / Settings / Book (hidden on Reader & Now Playing tab)
- **Expanded sheet** — tap mini bar, Resume, or reader dock
- **Badge** — labeled “Placeholder” until wired to real audio

Play/pause toggles sync across mini, sheet, reader dock, and Now Playing tab.

## Maps to audit doc

See `docs/2026-05-18-visual-audit-and-redesign-direction.md` — this sketch implements Phase 1–2 direction: unified tokens, continue-first book page, demoted technical blocks, three-tab shell (Library · Now Playing · Settings).
