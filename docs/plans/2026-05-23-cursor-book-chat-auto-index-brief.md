# Cursor implementation brief: Book Chat EPUB auto-index slice

Use Cursor CLI with model `composer-2.5` regular/non-fast.

## Current state

Repo: `/home/philip/audiobook-generator`

Recent commits:

- baseline git checkpoint exists
- Hermes/Codex model gateway proof works
- Book Chat backend indexing/retrieval exists
- Book Chat UI shell and memory API exists

Current user-visible problem:

- Opening Book Chat for a real book shows: `Could not get an answer. Index passages for this book first.`
- There is a TODO in `dashboard/index.html`: auto-index EPUB passages on first open.

Existing relevant files:

- `book_chat/embeddings.py`
- `book_chat/index_store.py`
- `book_chat/service.py`
- `book_chat/model_gateway.py`
- `book_chat/memory_store.py`
- `monitor_server.py`
- `dashboard/index.html`
- `epub_to_audiobook.py`

Useful existing functions/data:

- `monitor_server.read_catalog(root)` returns catalog books.
- Library book records use `epub_rel_path`; `/api/library/epub?id=<book_id>` already serves that EPUB.
- `epub_to_audiobook.extract_chapters(epub_path)` returns `(book_title, chapters)` where chapters have `index`, `title`, `source`, `text`.
- `book_chat.service.index_passages(root, book_id, raw_passages, embedder=...)` already embeds and writes the JSONL index.
- `book_chat.index_store.index_path_for_book(root, book_id)` returns `library/book_chat/<book_id>/passages.jsonl`.
- Tests are run with `./venv/bin/python -m pytest tests/ -q`.

## Goal

Make Book Chat able to index the selected book's EPUB automatically and then query real extracted passages.

## Required backend behavior

### 1. EPUB extraction module

Create `book_chat/epub_extractor.py` or similar.

Expose at least:

```python
def extract_passages_from_epub(epub_path: Path, *, max_chars: int = 1200, overlap_chars: int = 150) -> list[dict]:
    ...
```

Expected passage dict fields:

- `chapter`: readable chapter title
- `text`: chunk text
- optional but useful: `chapter_index`, `source`, `chunk_index`

Implementation guidance:

- Reuse `epub_to_audiobook.extract_chapters(epub_path)` if practical; do not duplicate the whole EPUB parser.
- Split chapter text into chunks around 800–1200 chars.
- Avoid tiny chunks. Merge or drop chunks under ~80 chars unless they are the only text.
- Preserve chapter title in each passage.
- Keep this synchronous for now.

### 2. Index status service/API

Add service/helper to inspect index status for a book.

Add endpoint:

```text
GET /api/library/book-chat/index-status?book_id=<id>
```

Response when indexed:

```json
{
  "ok": true,
  "book_id": "...",
  "indexed": true,
  "passage_count": 123,
  "embedding_model": "BAAI/bge-base-en-v1.5",
  "index_path": "library/book_chat/.../passages.jsonl"
}
```

Response when not indexed:

```json
{
  "ok": true,
  "book_id": "...",
  "indexed": false,
  "passage_count": 0
}
```

### 3. Auto-index API

Add endpoint:

```text
POST /api/library/book-chat/auto-index
```

Body:

```json
{ "book_id": "...", "force": false }
```

Behavior:

- Validate `book_id`.
- Find the book in `read_catalog(root)`.
- Find its `epub_rel_path`.
- Verify the resolved EPUB path stays under `root` and exists.
- If already indexed and `force` is false, return current index status with something like `status: "already_indexed"`.
- Else extract passages from EPUB and call `index_passages(...)` using `book_chat_embedder_factory()`.
- Return `ok`, `book_id`, `status`, `passage_count`, `embedding_model`, maybe `book_title`.
- Useful errors:
  - missing book_id: 400
  - book not found: 404
  - no epub: 404
  - epub missing: 404
  - extraction failed/no passages: 422 or 500 with clear message

### 4. UI integration

In `dashboard/index.html`:

- Replace/remove the TODO line that says auto-index is not implemented.
- Add stable marker/button/status, e.g.:
  - `id="bookChatIndexStatus"`
  - `id="bookChatIndexBtn"`
- When `openBookChatScreen(id)` runs:
  - call `/api/library/book-chat/index-status?book_id=<id>`
  - show whether the passage index is ready.
  - if not indexed, show/enable **Index this book**.
- Add function to POST `/api/library/book-chat/auto-index`.
- After successful indexing, update status and allow Send.
- If user presses Send while not indexed, attempt auto-index or show the Index button with a clear message.
- Keep mobile-first layout.

Do not over-polish. Make the current visible failure go away for books with EPUBs.

## Testing requirements

Add/update tests. Use fake/stub embedders and small synthetic EPUBs where possible. Do not require the real BGE model in unit tests.

Suggested tests:

- `tests/test_book_chat_epub_extractor.py`
  - create a tiny EPUB using `ebooklib` with 1–2 XHTML documents
  - verify extraction returns passages with chapter/title/text
  - verify long text is chunked

- `tests/test_book_chat_service.py` or `tests/test_book_chat_index_store.py`
  - verify index status reports indexed/unindexed

- `tests/test_monitor_server_book_chat_api.py`
  - create temp library/catalog with a fake book and EPUB under `library/uploads/...`
  - monkeypatch `monitor_server.book_chat_embedder_factory` to fake embedder
  - GET index-status before indexing: indexed false
  - POST auto-index: indexed/status ok with passage_count > 0
  - GET index-status after indexing: indexed true
  - POST query now returns citations from EPUB text

- `tests/test_dashboard_reader_and_settings_shell.py`
  - assert UI markers exist:
    - `bookChatIndexStatus`
    - `bookChatIndexBtn`
    - `/api/library/book-chat/index-status`
    - `/api/library/book-chat/auto-index`

Run:

```bash
./venv/bin/python -m pytest tests/ -q
```

## Verification after Cursor finishes

Hermes will independently run:

```bash
./venv/bin/python -m pytest tests/ -q
```

Then a live smoke test with `monitor_server.py`:

1. create temp library/catalog with a tiny EPUB
2. run server
3. GET index-status false
4. POST auto-index
5. POST query and verify citation text comes from EPUB

## Constraints

- Use Cursor model `composer-2.5`, not `composer-2.5-fast`.
- Keep changes focused.
- Preserve existing tests.
- No secrets.
- Do not add a background job system yet unless absolutely necessary.
- Do not wire real GPT/Gemini answer generation in this slice; this slice is about EPUB auto-indexing and UI status.

## Done criteria

- Book Chat can auto-index a selected book's EPUB.
- UI exposes index status and an Index this book action.
- Query works after auto-indexing.
- Full test suite passes.
- Git diff is focused and reviewable.
