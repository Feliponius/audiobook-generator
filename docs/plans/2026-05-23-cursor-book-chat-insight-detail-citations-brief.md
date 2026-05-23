# Cursor implementation brief: Book Chat insight detail modal and clickable citations

Use Cursor CLI with model `composer-2.5` regular/non-fast.

## Context

Repo: `/home/philip/audiobook-generator`

User feedback:

1. Saved insights should not be fully expanded on Book Chat startup.
2. Saved insights should show a relevant title/theme created at question time, not just the entire answer/question.
3. Tapping a saved insight title should open a large mobile-friendly modal/detail window that takes most/all of the screen.
4. In that modal, the user should scroll through the answer, see passages/citations at the bottom, and tap a passage to go to the reader.
5. Passage links should also be clickable from the initial answer citations.
6. If the user taps reader back after jumping from an insight/passage, they should return to the Book Chat/answer context, ideally reopening the saved insight modal when relevant.

Important technical reality:

- Current passage records in `library/book_chat/<book_id>/passages.jsonl` only include `id`, `book_id`, `chapter`, `text`, `embedding_model`, `embedding`.
- They do **not** include EPUB CFI/href/page. Exact page jumps are therefore not available yet.
- Implement best-effort navigation now: citation click opens the reader and attempts to display the matching chapter via EPUB navigation label. If not found, open the reader normally and show a toast. Do not fake exact page support.

Relevant files:

- `dashboard/index.html` main UI/JS/CSS.
- `book_chat/memory_store.py` currently stores only text/source/created_at. Extend compatibly.
- `monitor_server.py` POST `/api/library/book-chat/memory` currently accepts book_id/text/source. Extend compatibly.
- `book_chat/service.py` query returns answer + citations. Citations include `passage_id`, `chapter`, `snippet`.
- Tests:
  - `tests/test_dashboard_reader_and_settings_shell.py`
  - `tests/test_monitor_server_book_chat_api.py`
  - `tests/test_book_chat_service.py` if needed.

## Required product behavior

### Saved section collapsed by default

Change saved insights details element from open-by-default to closed-by-default:

```html
<details class="book-chat-saved" id="bookChatSavedInsightsSection">
```

Do not include the `open` attribute.

### Save richer insight metadata

When a Book Chat answer is generated, keep these in state:

- `state.bookChatLastQuestion`
- `state.bookChatLastAction`
- `state.bookChatLastAnswer`
- `state.bookChatLastCitations`

When saving, POST memory with:

```json
{
  "book_id": "...",
  "text": "full answer text",
  "source": "insight",
  "title": "short thematic title",
  "question": "original question",
  "action": "socratic|answer|...",
  "citations": [ ... ]
}
```

Backend should preserve these optional fields in the record:

- `title` string, optional
- `question` string, optional
- `action` string, optional
- `citations` list, optional; store only safe serializable dict fields: `passage_id`, `chapter`, `snippet`

Keep backward compatibility for old saved insights. Old records without title/citations should still render.

### Title/theme generation

Add frontend helper:

```js
function buildBookChatInsightTitle(question, answer, action) { ... }
```

It should produce a short theme-like title, not a long copy of question/answer. Good examples:

- `Influencing Difficult Coworkers`
- `Testing Assumptions About Workload`
- `Building Cooperation Without Authority`
- `Boundaries and Follow-Through`

Implementation can be deterministic; no extra model call required. Suggested approach:

- use action as weak hint only, not as title
- remove common filler words from question
- recognize phrases like `difficult`, `lazy`, `coworker`, `authority`, `influence`, `assumptions`, `practice`, `boundaries`, `cooperation`
- title-case 2–5 meaningful words
- fallback to first answer heading or `Saved Book Insight`
- max about 56 chars

This does not need to be perfect; it just needs to be more useful than the full answer.

### Saved list cards

Change saved insight cards so the main visible item is a clickable title/button, not the full answer text.

Each saved card should show:

- title button
- maybe small meta line: date/action/source
- maybe one-line preview, but not the full text
- Delete button

Clicking title opens modal.

### Fullscreen-ish modal/detail view

Add modal elements to `dashboard/index.html` near Book Chat shell or root:

Required IDs/classes for tests:

- `bookChatInsightModal`
- `bookChatInsightModalTitle`
- `bookChatInsightModalMeta`
- `bookChatInsightModalQuestion`
- `bookChatInsightModalAnswer`
- `bookChatInsightModalCitations`
- `bookChatInsightModalClose`

Mobile behavior:

- fixed overlay, high z-index
- on small screens use full viewport/inset 0 or near-fullscreen
- internal scroll body
- close button returns to Ask screen

Functions:

```js
function openBookChatInsightModal(memoryId) { ... }
function closeBookChatInsightModal() { ... }
function renderBookChatInsightModal(memory) { ... }
```

Modal content:

- title at top
- metadata/date/action
- original question if present
- full saved answer text, scrollable
- citations/passages at bottom as clickable chips/cards

### Clickable citations from initial answer and modal

Currently `renderBookChatCitations(data.citations)` exists. Change it so each citation is a button/card and calls:

```js
openBookChatPassageCitation(citation, { returnMemoryId: null })
```

Modal citations call:

```js
openBookChatPassageCitation(citation, { returnMemoryId: memory.memory_id })
```

Required helper names for tests:

- `renderBookChatCitationButton`
- `openBookChatPassageCitation`
- `findReaderTocHrefForCitation`

### Reader return behavior

Add state:

```js
state.bookChatReturnContext = null
```

When opening reader from citation:

```js
state.bookChatReturnContext = {
  bookId: state.currentBookId,
  memoryId: returnMemoryId || null,
  citation
}
```

Navigate/open reader. On reader back:

- if `state.bookChatReturnContext` exists:
  - grab it
  - clear it
  - navigate to `#/bookchat/<bookId>`
  - after Book Chat screen loads and saved insights load, reopen modal if `memoryId` exists
- else preserve existing behavior: go back to book detail.

Simple approach:

- add `state.pendingBookChatInsightModalId = null`
- readerBack sets pending id and navigates bookchat
- `loadBookChatSavedInsights`/`openBookChatScreen` opens the pending modal after memories render.

### Reader chapter jump best-effort

Modify `openReader(id, opts)` to accept optional opts:

```js
async function openReader(id, opts) { ... }
```

Where opts may include:

```js
{
  citation: { chapter, passage_id, snippet }
}
```

After EPUB nav is loaded and `flat = flattenToc(...)` exists, try:

```js
const href = findReaderTocHrefForCitation(flat, opts.citation)
if (href) await state.rendition.display(href)
else showToast('Opened reader; exact passage location is not available yet')
```

`findReaderTocHrefForCitation(flat, citation)` should match chapter labels conservatively:

- normalize lowercase, strip punctuation/extra spaces
- exact contains either direction between citation.chapter and item.label
- return first href

Do not break existing read route. If route calls `openReader(r.id)`, behavior unchanged.

For citation clicks, it is acceptable to call `openReader(id, { citation })` directly rather than changing hash route, as long as reader opens and back behavior works. But watch routeUI/hideReader interactions. If direct call is simpler, do it.

## Backend changes

### memory_store.py

Change:

```py
def save_memory(root, book_id, text, *, source='user')
```

to accept optional metadata:

```py
def save_memory(root, book_id, text, *, source='user', title=None, question=None, action=None, citations=None)
```

Validate softly:

- string fields strip and store only if non-empty
- citations only if list; store sanitized list of dicts with string fields `passage_id`, `chapter`, `snippet`; truncate snippet to maybe 1000 chars
- preserve existing behavior/tests.

### monitor_server.py

POST `/api/library/book-chat/memory` should read optional `title`, `question`, `action`, `citations` and pass them to save_memory.

## Tests

Use TDD where practical.

### Backend test: `tests/test_monitor_server_book_chat_api.py`

Extend memory CRUD or add a new test to POST a memory with title/question/action/citations and assert GET returns those fields.

Also verify old minimal memory POST still works.

### Unit test: `tests/test_book_chat_memory_store.py` if exists, or add to API tests

Validate citation sanitization if easy.

### Dashboard marker test: `tests/test_dashboard_reader_and_settings_shell.py`

Add assertions for:

- `id="bookChatSavedInsightsSection"` present but `id="bookChatSavedInsightsSection" open` not present.
- `bookChatInsightModal`
- `bookChatInsightModalTitle`
- `bookChatInsightModalCitations`
- `bookChatInsightModalClose`
- `buildBookChatInsightTitle`
- `openBookChatInsightModal`
- `closeBookChatInsightModal`
- `renderBookChatInsightModal`
- `renderBookChatCitationButton`
- `openBookChatPassageCitation`
- `findReaderTocHrefForCitation`
- `bookChatReturnContext`
- `pendingBookChatInsightModalId`

Also assert save POST contains title/question/action/citations keys.

## Verification

Run:

```bash
./venv/bin/python -m pytest tests/test_dashboard_reader_and_settings_shell.py tests/test_monitor_server_book_chat_api.py -q
./venv/bin/python -m pytest tests/ -q
```

Live smoke after restart on 8123:

1. Fetch `/index.html` and confirm modal IDs and helpers present.
2. POST memory for book `68789d92-2b98-4d7c-a29c-4d5310e61765` with title/question/action/citations.
3. GET memory and verify fields are returned.
4. DELETE smoke memory.

## Constraints

- Keep changes focused and compatible with old saved insights.
- Do not invent exact page jumps; best-effort chapter jump only unless the data exists.
- Use `composer-2.5`, not fast.
- Do not commit temp helper scripts.
- Preserve all existing Book Chat indexing/query behavior.
