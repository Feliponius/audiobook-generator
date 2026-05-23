# Cursor implementation brief: Book Chat exact-ish passage links and citation metadata

Use Cursor CLI with model `composer-2.5` regular/non-fast.

## Context

Repo: `/home/philip/audiobook-generator`

User wants saved insight citations to actually link back to the relevant spot in the book, not just show a passage blob. Current state:

- `book_chat/epub_extractor.py::passages_from_chapters()` already includes metadata from `extract_chapters()`:
  - `chapter_index`
  - `source` — EPUB XHTML filename from `Chapter.source`, e.g. `chapter_1.xhtml` or `titlepage_text.xhtml`
  - `chunk_index`
- `book_chat/service.py::index_passages()` currently drops that metadata and stores only `id`, `book_id`, `chapter`, `text`, `embedding_model`, `embedding`.
- `book_chat/index_store.py::retrieve_top_k()` currently returns only `passage_id`, `score`, `chapter`, `text`, `snippet`.
- `book_chat/service.py::_citation_from_hit()` currently returns only `passage_id`, `chapter`, `snippet`.
- `book_chat/memory_store.py` currently only persists citation keys `passage_id`, `chapter`, `snippet`.
- `dashboard/index.html` clickable citations currently best-effort match TOC chapter labels via `findReaderTocHrefForCitation(flat, citation)`, then `rendition.display(citeHref)`.

## Goal

Make citations link to the exact EPUB document source for a passage whenever possible, and carry enough metadata for future exact paragraph/page jumps.

This is an incremental but useful upgrade:

1. New index records should preserve `source`, `chapter_index`, and `chunk_index` from raw passages.
2. Retrieval hits and citations should include these metadata fields:
   - `source`
   - `href` (alias/source link for the reader; use the raw `source` value)
   - `chapter_index`
   - `chunk_index`
3. Saved insight citations should persist those fields.
4. Reader citation click should prefer `citation.href` / `citation.source` over fuzzy TOC chapter matching.
5. If `href` exists, `openReader(bookId, { citation })` should call `state.rendition.display(href)` after EPUB load, then show a toast only if exact paragraph anchoring is unavailable. Do not toast as if it failed when the source XHTML opened successfully.
6. Keep old citations compatible.

## Important limitation wording

Do not claim true exact paragraph/page CFI support yet unless actually implemented. This task should achieve exact EPUB source-document navigation. True paragraph/page jump still requires CFI/range anchoring. Preserve room for that by carrying `chunk_index` and `snippet`.

If you can safely add snippet-based in-rendered-document location without brittle code, do it behind a helper and tests. But the must-have is source href navigation, because that is reliable and immediately improves the user’s saved insight.

## Tests first

Add/update tests before production code.

### 1. `tests/test_book_chat_service.py`

Add a test for metadata preservation through `index_passages`:

- call `index_passages()` with raw passage:

```python
{
  "chapter": "Chapter 5",
  "text": "A useful passage about influence.",
  "source": "chapter_5.xhtml",
  "chapter_index": 5,
  "chunk_index": 3,
}
```

- read stored record with `read_passages(index_path_for_book(...))`
- assert stored has:
  - `source == "chapter_5.xhtml"`
  - `href == "chapter_5.xhtml"` or if you decide not to duplicate in stored records, at least retrieval/citation has href
  - `chapter_index == 5`
  - `chunk_index == 3`

Add/extend query test so returned `citations[0]` includes these same metadata fields after retrieval.

### 2. `tests/test_book_chat_memory_store.py`

Update metadata persistence test so citations with `source`, `href`, `chapter_index`, `chunk_index` round-trip. Sanitizer should keep only safe scalar fields. `chapter_index`/`chunk_index` may be ints or strings; prefer ints if incoming value is int.

### 3. `tests/test_dashboard_reader_and_settings_shell.py`

Add marker assertions for:

- citation href/source preference in reader logic, e.g. `citation.href || citation.source`
- `state.rendition.display(citeHref)` or equivalent
- old fuzzy `findReaderTocHrefForCitation` remains as fallback

## Implementation details

### `book_chat/service.py`

In `index_passages()`, preserve metadata from each raw passage:

```python
record = {
  "id": _passage_id(book_id, i),
  "book_id": book_id,
  "chapter": chapter,
  "text": text,
  "embedding_model": emb.model_name,
  "embedding": emb.embed(text),
}
source = str(item.get("source") or "").strip()
if source:
    record["source"] = source
    record["href"] = source
for key in ("chapter_index", "chunk_index"):
    val = item.get(key)
    if isinstance(val, int): record[key] = val
    elif isinstance(val, str) and val.strip().isdigit(): record[key] = int(val.strip())
```

In `_citation_from_hit()`, include metadata if present:

```python
for key in ("source", "href", "chapter_index", "chunk_index"):
    if key in hit and hit[key] not in (None, ""):
        citation[key] = hit[key]
```

### `book_chat/index_store.py`

In `retrieve_top_k()`, include metadata in hit dict. Keep backwards compatible.

### `book_chat/memory_store.py`

Extend sanitizer to preserve citation metadata:

- string keys: `passage_id`, `chapter`, `snippet`, `source`, `href`
- integer keys: `chapter_index`, `chunk_index`

Keep snippet truncation.

### `dashboard/index.html`

Update citation rendering to keep data unchanged and clickable.

Update `openReader(id, opts)` citation handling:

Current code builds `flat`, then:

```js
const citeHref = findReaderTocHrefForCitation(flat, opts.citation);
if (citeHref && state.rendition) {
  await state.rendition.display(citeHref).catch(() => {});
} else {
  showToast('Opened reader; exact passage location is not available yet');
}
```

Change to prefer citation source/href:

```js
const directHref = citationHrefForReader(opts.citation); // citation.href || citation.source, trim, reject empty
const citeHref = directHref || findReaderTocHrefForCitation(flat, opts.citation);
let openedCitationHref = false;
if (citeHref && state.rendition) {
  openedCitationHref = await state.rendition.display(citeHref).then(() => true).catch(() => false);
}
if (!openedCitationHref) {
  showToast('Opened reader; exact passage location is not available yet');
} else if (!directHref) {
  showToast('Opened the closest matching chapter');
}
```

If you add snippet-location helper, do it after `display(citeHref)` and keep errors swallowed; never break reader opening.

Add helper markers for tests:

```js
function citationHrefForReader(citation) { ... }
```

Preserve reader-back behavior to Book Chat/saved modal.

## Backfill note

Hermes already backfilled the current saved insight record with title/citations from embedded source IDs. After implementation, Hermes will force-reindex the current book so new passage records include `source/href/chunk_index`, then backfill existing saved citations from the updated passage records.

## Verification

Run:

```bash
./venv/bin/python -m pytest tests/test_book_chat_service.py tests/test_book_chat_memory_store.py tests/test_dashboard_reader_and_settings_shell.py tests/test_monitor_server_book_chat_api.py -q
./venv/bin/python -m pytest tests/ -q
```

Then Hermes will run live API smoke and restart port 8123.

## Constraints

- Keep changes focused.
- Do not create temp helper scripts committed to repo.
- Do not use `composer-2.5-fast`.
- Do not break legacy saved insights or legacy indexes without metadata.
