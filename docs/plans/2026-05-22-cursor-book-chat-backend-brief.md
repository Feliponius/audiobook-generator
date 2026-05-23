# Cursor implementation brief: Book Chat v1 backend slice

Use Cursor as code-change executor with model `composer-2.5` regular/non-fast.

## Context

Repo: `/home/philip/audiobook-generator`

The plan/spec is at:

- `docs/plans/2026-05-22-book-chat-v1-spec.md`

A verified proof-of-concept already exists:

- `book_chat/model_gateway.py`
- `tests/test_book_chat_model_gateway.py`

Verified live call:

```bash
./venv/bin/python - <<'PY'
from book_chat.model_gateway import ask_via_hermes_codex
result = ask_via_hermes_codex('Reply with exactly: CODEX_WRAPPER_POC_OK', timeout_seconds=120)
assert result.ok
assert 'CODEX_WRAPPER_POC_OK' in result.text
PY
```

Local BGE smoke test has already succeeded with `BAAI/bge-base-en-v1.5` and dimension 768.

## Goal for this Cursor pass

Implement the smallest solid backend slice for Book Chat v1:

1. Local BGE embedding/retrieval module.
2. JSONL passage index storage.
3. Minimal monitor_server API endpoints for indexing/querying a book-chat index.
4. Tests proving behavior without live LLM calls.

Do NOT build the full polished UI in this pass unless the backend/tests are complete and time remains.

## Constraints

- Preserve existing app behavior and tests.
- Use strict, incremental changes.
- Keep generated outputs, books, venvs, and secrets out of git.
- Do not hardcode personal API keys or secrets.
- Do not require live Codex/Gemini calls in automated tests.
- Use local `BAAI/bge-base-en-v1.5` by default, but design tests so they can use fake embedders instead of downloading/running the model.
- Keep Hermes/Codex wrapper as primary model gateway proof, but do not make unit tests shell out to Hermes.
- Include `fallback_used`, provider, and model metadata in query responses where applicable.

## Suggested implementation shape

Add modules under `book_chat/`:

- `embeddings.py`
  - `LocalBGEEmbedder`
  - fake/test-friendly embedder interface
- `index_store.py`
  - JSONL read/write helpers
  - passage record schema
  - cosine similarity retrieval
- `service.py`
  - chunk/sample indexing helpers
  - `index_passages(...)`
  - `query_passages(...)`

Integrate in `monitor_server.py` with minimal endpoints:

- `POST /api/library/book-chat/index`
  - body: `{ "book_id": "...", "passages": [{"chapter": "...", "text": "..."}] }`
  - v1 test path can accept direct passages so EPUB extraction can be handled later.
  - stores index under library/book-specific or book_chat index dir.

- `POST /api/library/book-chat/query`
  - body: `{ "book_id": "...", "question": "...", "top_k": 3 }`
  - retrieves relevant passages from JSONL index.
  - for now returns a grounded draft answer shape even if it does not call LLM in tests:
    - `answer`
    - `citations`
    - `retrieved_passages`
    - `model_provider`
    - `model`
    - `fallback_used`

If wiring the live model call is straightforward, put it behind a flag like `use_model: true`; default tests should use retrieval-only/deterministic mode.

## Tests to add/update

Add tests such as:

- `tests/test_book_chat_index_store.py`
- `tests/test_book_chat_service.py`
- `tests/test_monitor_server_book_chat_api.py`

Test cases:

1. JSONL passage index writes and reads records.
2. Retrieval returns the semantically closest passage using a fake deterministic embedder.
3. Index endpoint stores passages for a book.
4. Query endpoint returns citations and top passages.
5. Missing index/book returns a useful error.
6. Existing monitor_server tests still pass.

Run verification:

```bash
./venv/bin/python -m pytest tests/test_book_chat_model_gateway.py tests/test_book_chat_index_store.py tests/test_book_chat_service.py tests/test_monitor_server_book_chat_api.py -q
./venv/bin/python -m pytest tests/ -q
```

## Done criteria

- New backend slice implemented.
- Tests pass.
- Existing tests pass.
- Git diff is focused and reviewable.
- Summarize changed files and any follow-up tasks.
