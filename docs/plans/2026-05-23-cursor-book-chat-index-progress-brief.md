# Cursor implementation brief: Book Chat background indexing progress

Use Cursor CLI with model `composer-2.5` regular/non-fast.

## Context

Repo: `/home/philip/audiobook-generator`

Book Chat currently works but the first full-book BGE indexing pass is slow. Live test on `Influence Without Authority` took ~445.7 seconds and generated 559 passages. The UI currently calls `/api/library/book-chat/auto-index` as a single long POST. On mobile this feels broken, can lose the connection, and offers no progress.

Current relevant files:

- `book_chat/service.py`
  - `auto_index_book_epub(root, book_id, epub_path, force=False, embedder=None)`
  - `index_passages(root, book_id, raw_passages, embedder=None)` loops passages and embeds one at a time.
- `book_chat/embeddings.py`
  - `TextEmbedder`, `FakeHashEmbedder`, `LocalBGEEmbedder`
- `book_chat/index_store.py`
  - `index_path_for_book`, `write_passages`, `read_passages`
- `monitor_server.py`
  - GET `/api/library/book-chat/index-status`
  - POST `/api/library/book-chat/auto-index`
  - `book_chat_embedder_factory()` now reuses one process-wide BGE embedder.
- `dashboard/index.html`
  - Book Chat screen has `bookChatIndexStatus`, `bookChatIndexBtn`, `runBookChatAutoIndex`, `refreshBookChatIndexStatus`.

User wants a visual progress bar for indexing.

## Goal

Replace the long blocking index button UX with a background indexing job and visual progress polling.

## Required UX

When the user taps **Index this book**:

- start indexing in a background server thread and return immediately
- show a visible progress bar on the Book Chat screen
- poll job progress every 1–2 seconds
- show stage and message, e.g.:
  - Preparing EPUB…
  - Extracting chapters…
  - Chunking passages…
  - Embedding passages 137 / 559…
  - Saving index…
  - Passage index ready (559 passages)
- if the user refreshes/reopens while a job is running, status polling should recover from the persisted job file
- if already indexed, do not re-index unless forced; show ready
- keep the existing `/api/library/book-chat/auto-index` endpoint as a compatibility synchronous endpoint if practical, but the UI should use the new background endpoints.

## Backend design

Create a small module:

- `book_chat/index_job.py`

Persist job state at:

- `library/book_chat/<book_id>/index_job.json`

Job JSON shape should be stable and testable:

```json
{
  "ok": true,
  "book_id": "...",
  "status": "idle|running|done|error",
  "stage": "idle|preparing|extracting|chunking|embedding|saving|complete|error",
  "message": "Embedding passages 137 / 559",
  "current": 137,
  "total": 559,
  "percent": 24,
  "started_at": "...",
  "updated_at": "...",
  "error": null
}
```

Exact field names matter because the frontend will use them.

Implement helpers:

- `job_path_for_book(root, book_id) -> Path`
- `default_job_status(root, book_id) -> dict`
- `read_index_job(root, book_id) -> dict`
- `write_index_job(root, book_id, status_dict) -> dict`
- `update_index_job(root, book_id, **fields) -> dict`
- `complete_index_job(root, book_id, passage_count, embedding_model) -> dict`
- `fail_index_job(root, book_id, error) -> dict`

Keep it simple: JSON file storage, atomic-ish write via temp file + replace if easy.

## Progress callback

Modify `book_chat/service.py` so `index_passages` and `auto_index_book_epub` accept an optional progress callback.

Suggested callback signature:

```python
ProgressCallback = Callable[[dict[str, Any]], None]
```

Call it at key stages:

- preparing/extracting before EPUB extraction
- chunking after extraction begins
- embedding once `raw_passages` length is known
- every passage or every N passages during embedding
- saving before `write_passages`
- complete after write

Important: tests use `FakeHashEmbedder`, so do not add sleeps.

## New HTTP endpoints

Add to `monitor_server.py`:

### POST `/api/library/book-chat/index-job`

Body:

```json
{"book_id":"...", "force": false}
```

Behavior:

- validate `book_id`
- if current index exists and force is false, write/read done status and return immediately with `status: done`, `percent: 100`, `passage_count`
- if a job JSON says `running`, return the existing running status rather than starting duplicate thread
- otherwise resolve the book and EPUB path using the same validations as existing `/auto-index`
- write a `running` job state
- start a daemon `threading.Thread` that calls `auto_index_book_epub(...)` with `book_chat_embedder_factory()` and progress callback that writes job state
- thread catches exceptions and writes `status: error`
- endpoint returns the first running job state immediately

### GET `/api/library/book-chat/index-job-status?book_id=<id>`

Behavior:

- if index exists, prefer returning done/100 with passage count, even if old job state is stale
- else return job file if present
- else return idle/unindexed state

## Frontend design

Modify `dashboard/index.html` Book Chat panel:

- add a progress bar container under `bookChatIndexStatus`, something like:

```html
<div class="book-chat-progress hidden" id="bookChatIndexProgress" aria-hidden="true">
  <div class="book-chat-progress-bar" id="bookChatIndexProgressBar"></div>
</div>
<p class="book-chat-progress-label hidden" id="bookChatIndexProgressLabel"></p>
```

- add CSS that looks good on mobile, simple rounded bar.
- update JS:
  - add `state.bookChatIndexPollTimer`
  - `renderBookChatIndexJob(job)` updates progress UI and status text
  - `startBookChatIndexPolling(bookId)` polls `/index-job-status`
  - `stopBookChatIndexPolling()` clears timer
  - `runBookChatAutoIndex(bookId)` should POST `/index-job`, then start polling; do not wait minutes on `/auto-index`
  - `openBookChatScreen(id)` should call status and also check `/index-job-status` so refresh/reopen resumes progress
  - when status done, call `setBookChatIndexUi(true, passage_count)` and hide/show button appropriately
  - when error, show message and re-enable index button

Keep existing send behavior: if user presses Send while unindexed, it can start indexing and then tell them indexing is running; do not block for minutes.

## Tests to add/update

Use TDD. Add tests before implementation.

Suggested tests:

1. `tests/test_book_chat_index_job.py`
   - default status is idle with percent 0
   - write/read round trip
   - update computes/preserves fields
   - complete status gives done/100
   - fail status gives error

2. `tests/test_book_chat_service.py`
   - `index_passages(..., progress_callback=cb)` emits embedding progress with current/total/percent and final saving/complete signal.

3. `tests/test_monitor_server_book_chat_api.py`
   - POST `/api/library/book-chat/index-job` returns quickly with running or done for fake-test environment.
   - GET `/index-job-status` returns done after test indexing completes.
   - Duplicate POST while running returns existing running state. If this is hard due fast fake embedder, test helper functions instead; do not make tests flaky.

4. `tests/test_dashboard_reader_and_settings_shell.py`
   - HTML contains `bookChatIndexProgress`, `bookChatIndexProgressBar`, `bookChatIndexProgressLabel`
   - JS contains `/api/library/book-chat/index-job` and `/api/library/book-chat/index-job-status`
   - JS contains polling cleanup function/timer.

## Verification commands

Run:

```bash
./venv/bin/python -m pytest tests/test_book_chat_index_job.py tests/test_book_chat_service.py tests/test_monitor_server_book_chat_api.py tests/test_dashboard_reader_and_settings_shell.py -q
./venv/bin/python -m pytest tests/ -q
```

Then live smoke with a temporary EPUB and fake/small data if possible:

- start monitor_server on an unused port/root
- create tiny EPUB + catalog
- POST `/api/library/book-chat/index-job`
- poll `/api/library/book-chat/index-job-status` until done
- assert percent 100 and index-status indexed

## Constraints

- Keep changes focused.
- Do not use Composer 2.5 Fast. Use `composer-2.5` regular/non-fast.
- Preserve existing endpoints unless impossible.
- Do not commit temporary helper scripts.
- Do not break current indexed book query flow.
- Avoid introducing heavyweight web framework; keep the current server style.
