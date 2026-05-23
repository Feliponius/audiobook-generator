# Cursor implementation brief: Book Chat v1 UI + memory slice

Use Cursor CLI with model `composer-2.5` regular/non-fast.

## Current state

Backend slice is implemented and verified:

- `book_chat/embeddings.py`
- `book_chat/index_store.py`
- `book_chat/service.py`
- `book_chat/model_gateway.py`
- `POST /api/library/book-chat/index`
- `POST /api/library/book-chat/query`

Tests currently pass:

```bash
./venv/bin/python -m pytest tests/ -q
```

Book Chat spec:

- `docs/plans/2026-05-22-book-chat-v1-spec.md`

## Goal for this Cursor pass

Implement the next smallest user-visible slice:

1. Minimal memory storage API for book-specific saved insights.
2. Minimal mobile-first UI entry point for Book Chat in `dashboard/index.html`.
3. UI can ask the backend query endpoint and display answer + citations.
4. UI includes learning action buttons as static prompts/quick-fill helpers.
5. Tests updated for HTML markers and backend memory behavior.

## Constraints

- Use `composer-2.5`, not fast.
- Keep the UI simple and mobile-first; do not over-polish.
- Preserve existing dashboard tests and behavior.
- Do not require live Codex/Gemini calls in tests.
- Do not add secrets.
- If real book text extraction/indexing from EPUB is too broad, keep the UI/API oriented around already-indexed passages and add a clear TODO.

## Memory API shape

Add simple JSONL-backed memory helpers under `book_chat/` if useful, e.g. `memory_store.py`.

Endpoints:

- `GET /api/library/book-chat/memory?book_id=<id>`
  - returns `{ ok, book_id, memories: [...] }`

- `POST /api/library/book-chat/memory`
  - body: `{ "book_id": "...", "text": "...", "source": "user|assistant|insight" }`
  - returns saved memory record

- Optional delete endpoint if easy:
  - `DELETE /api/library/book-chat/memory?book_id=<id>&memory_id=<id>`

Memory record fields:

- `memory_id`
- `book_id`
- `text`
- `source`
- `created_at`

## UI requirements

In `dashboard/index.html`:

- Add an `Ask this book` / `Book Chat` entry point visible from a selected book/detail/reader context if the structure supports it.
- Add a lightweight chat panel/screen with:
  - question textarea/input
  - send button
  - answer area
  - citations list/cards
  - quick action buttons:
    - `Explain this another way`
    - `Ask me Socratic questions`
    - `Challenge my assumptions`
    - `Give me a real-life example`
    - `Turn this into a practice exercise`
    - `Save this insight`
- Add stable IDs/data markers so tests can verify the UI exists.

If the current dashboard does not have a clean selected-book state for chat, add the UI shell and JS functions without forcing a perfect navigation flow. The goal is a thin vertical slice, not a perfect consumer design.

## Tests to add/update

- `tests/test_book_chat_memory_store.py`
- `tests/test_monitor_server_book_chat_api.py` for memory endpoints
- `tests/test_dashboard_reader_and_settings_shell.py` or new dashboard test for UI markers:
  - `id="bookChatPanel"`
  - `id="bookChatQuestion"`
  - `id="bookChatSendBtn"`
  - `id="bookChatCitations"`
  - learning action labels

## Verification

Run:

```bash
./venv/bin/python -m pytest tests/ -q
```

If feasible, also run a live HTTP smoke for memory endpoints.

## Done criteria

- Memory endpoints work and are tested.
- UI shell exists with markers and quick actions.
- Query JS calls `/api/library/book-chat/query`.
- Save insight JS calls memory endpoint or is clearly wired to do so.
- Full test suite passes.
- Git diff is focused.
