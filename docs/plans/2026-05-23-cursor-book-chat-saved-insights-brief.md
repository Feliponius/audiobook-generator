# Cursor implementation brief: Book Chat saved insights list

Use Cursor CLI with model `composer-2.5` regular/non-fast.

## Context

Repo: `/home/philip/audiobook-generator`

The user clicked **Save this insight** after a good Book Chat answer. The button says the insight was saved, but there is no visible way to access previously saved insights.

Important: the backend storage already exists. Do **not** create a second store.

Relevant files:

- `book_chat/memory_store.py`
  - stores JSONL records at `library/book_chat/<book_id>/memories.jsonl`
  - `list_memories(root, book_id)`
  - `save_memory(root, book_id, text, source='insight')`
  - `delete_memory(root, book_id, memory_id)`
- `monitor_server.py`
  - GET `/api/library/book-chat/memory?book_id=<id>` already returns `{ok, book_id, memories}`
  - POST `/api/library/book-chat/memory` saves an insight
  - DELETE `/api/library/book-chat/memory?book_id=<id>&memory_id=<id>` deletes one
- `dashboard/index.html`
  - `saveBookChatInsight()` POSTs insight and shows `Insight saved`
  - no list/render function exists for saved insights
  - Book Chat panel is around line ~1510
  - JS functions around `saveBookChatInsight`, `openBookChatScreen`
- Tests:
  - `tests/test_monitor_server_book_chat_api.py` already covers memory CRUD
  - `tests/test_dashboard_reader_and_settings_shell.py` checks UI markers

## Goal

Add a visible, mobile-friendly saved-insights section inside the Book Chat screen so saved insights can be seen, refreshed, and deleted.

## UX requirements

Inside Book Chat, below the answer/actions area, add a section like:

```html
<details class="book-chat-saved" id="bookChatSavedInsightsSection" open>
  <summary>Saved insights <span id="bookChatSavedInsightsCount">0</span></summary>
  <div id="bookChatSavedInsightsList">No saved insights yet.</div>
</details>
```

Exact markup can vary, but these IDs are required for tests and future work:

- `bookChatSavedInsightsSection`
- `bookChatSavedInsightsCount`
- `bookChatSavedInsightsList`

Each saved item should show:

- saved text, truncated/contained nicely on mobile
- source label if useful (`insight`)
- created date/time if present
- a **Delete** button per item

When no saved insights exist, show:

```text
No saved insights yet. Save an answer to keep it with this book.
```

When Save succeeds:

- refresh the saved insights list immediately
- update the count
- show toast `Insight saved`

When Delete succeeds:

- remove/refresh list
- update count
- show toast `Insight deleted`

When Book Chat screen opens:

- fetch and render saved insights for that book

## Frontend implementation details

Add JS helpers in `dashboard/index.html`:

```js
function renderBookChatSavedInsights(memories) { ... }
async function loadBookChatSavedInsights(bookId) { ... }
async function deleteBookChatSavedInsight(bookId, memoryId) { ... }
```

Implementation notes:

- Use existing `fetchJson`.
- GET from `/api/library/book-chat/memory?book_id=...`
- DELETE using existing endpoint.
- Avoid inline unsafe HTML for memory text; use `textContent` or existing `escapeHtml` carefully.
- Sort newest first if the backend returns oldest first.
- Store maybe `state.bookChatSavedInsights = []` if helpful.
- In `openBookChatScreen(id)`, call `loadBookChatSavedInsights(id)` after setting up UI.
- In `saveBookChatInsight()`, after successful POST call `await loadBookChatSavedInsights(id)`.

## Backend

No backend changes should be needed unless you discover a bug. Preserve existing API shape.

## Tests

Use TDD. Add/update tests before implementation where practical.

### `tests/test_dashboard_reader_and_settings_shell.py`

Add assertions that dashboard HTML contains:

- `id="bookChatSavedInsightsSection"`
- `id="bookChatSavedInsightsCount"`
- `id="bookChatSavedInsightsList"`
- `loadBookChatSavedInsights`
- `renderBookChatSavedInsights`
- `deleteBookChatSavedInsight`
- `DELETE`
- `/api/library/book-chat/memory?book_id=`
- `No saved insights yet. Save an answer to keep it with this book.`

### `tests/test_monitor_server_book_chat_api.py`

Existing CRUD test is probably enough, but if useful, assert GET order or deletion behavior remains stable. Do not overbuild.

## Verification

Run:

```bash
./venv/bin/python -m pytest tests/test_dashboard_reader_and_settings_shell.py tests/test_monitor_server_book_chat_api.py -q
./venv/bin/python -m pytest tests/ -q
```

Then live smoke:

1. Start/restart monitor server on port 8123.
2. Use existing indexed book `68789d92-2b98-4d7c-a29c-4d5310e61765`.
3. POST a test insight to `/api/library/book-chat/memory`.
4. GET `/api/library/book-chat/memory?book_id=...` and verify it appears.
5. Fetch `/index.html` and verify the saved insights IDs exist.

## Constraints

- Keep changes focused.
- Use `composer-2.5`, not `composer-2.5-fast`.
- Do not commit temporary helper scripts.
- Preserve existing save/delete API.
- Do not break Book Chat querying, indexing, or answer modes.
