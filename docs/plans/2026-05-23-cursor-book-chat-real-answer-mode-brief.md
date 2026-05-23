# Cursor implementation brief: Book Chat real answer mode

Use Cursor CLI with model `composer-2.5` regular/non-fast.

## Context

Repo: `/home/philip/audiobook-generator`

Book Chat currently indexes EPUB passages, retrieves relevant passages, and can call Hermes/Codex behind `use_model=True`, but the current prompt is generic:

```python
"Answer the user's question using only the book passages below..."
```

The mobile UI quick action buttons currently only prepend text like `Ask me Socratic questions about: ` into the textarea. The query POST body currently sends only `{ book_id, question }`, so the backend defaults to retrieval-only and the answer does not behave like the selected action. User screenshots confirmed: the app retrieved good passages but returned a generic retrieval draft instead of actual Socratic questions.

Relevant files:

- `book_chat/service.py`
  - `query_passages(...)`
  - `_retrieval_only_answer(...)`
  - `ask_via_hermes_codex(prompt, model=model)` import
- `book_chat/model_gateway.py`
  - `ask_via_hermes_codex(prompt, model="gpt-5.5", timeout_seconds=90, cwd=None)`
- `monitor_server.py`
  - POST `/api/library/book-chat/query` around line ~2186
  - currently parses `use_model = bool(body.get("use_model"))`
- `dashboard/index.html`
  - quick action buttons have `data-book-chat-action="explain|socratic|challenge|example|practice"`
  - `BOOK_CHAT_QUICK_PREFIX` currently only prepends text
  - `sendBookChatQuery()` POSTs `{ book_id: id, question }`
- `tests/test_book_chat_service.py`
- `tests/test_monitor_server_book_chat_api.py`
- `tests/test_dashboard_reader_and_settings_shell.py`

## Goal

Make Book Chat use real GPT-5.5/Codex answer mode by default for user questions and especially for quick actions, while preserving retrieval-only fallback if the gateway fails.

The quick action buttons should produce behavior-specific outputs:

- `socratic`: reflective questions, not a generic answer
- `challenge`: careful assumption checks / gentle pushback
- `example`: realistic concrete scenario
- `practice`: short practice exercise / next action
- `explain`: simpler re-explanation
- default/freeform: answer with sections grounded in citations

## Backend design

### Add answer action support

In `book_chat/service.py`, introduce a small action vocabulary:

```python
BOOK_CHAT_ACTIONS = {"answer", "explain", "socratic", "challenge", "example", "practice"}
DEFAULT_BOOK_CHAT_ACTION = "answer"
```

Add helper:

```python
def normalize_answer_action(action: str | None) -> str:
    ...
```

It should accept unknown/missing values and return `"answer"`.

### Add prompt builder

Create a pure helper in `book_chat/service.py`:

```python
def build_book_chat_prompt(question: str, hits: list[dict[str, Any]], *, action: str = "answer") -> str:
    ...
```

This must be independently unit-tested without live LLM.

Prompt requirements:

- Must instruct the model to answer using only the retrieved passages plus the user's question.
- Must tell the model not to invent claims not supported by passages.
- Must include `passage_id` references in the prompt context.
- Must require citations in the answer, preferably parenthetical source tags like `[passage_...]` or a final `Sources` section.
- Must be kind, direct, practical, and reflective.
- Must say if passages are insufficient.
- Must preserve the user's real-world context if they ask personal/work questions, without claiming the book says things it does not.

Suggested default answer structure:

```text
What the book says
How this may connect to your situation
Questions worth asking yourself
One small next step
Sources
```

Suggested action instructions:

- `socratic`: produce 6–8 Socratic questions grouped by theme; avoid lecturing; each question should be grounded in a cited passage when possible.
- `challenge`: identify 3–5 assumptions that may be worth testing; include a kinder alternative interpretation; cite passages.
- `example`: give one concrete realistic example scenario; then map it back to the passages; cite sources.
- `practice`: give a 10–15 minute practice exercise with steps; include what to say/do; cite sources.
- `explain`: re-explain the book idea simply; include a short analogy and citations.
- `answer`: use the default structured reflective answer.

### Improve retrieval fallback

Update `_retrieval_only_answer(question, hits, action="answer")` so fallback is at least action-aware:

- If `socratic`, return several question bullets based on top snippets.
- If `challenge`, return assumptions to test.
- If `example`, return a retrieval-grounded example-ish draft.
- If `practice`, return a small practice draft.
- If `explain`, return a simpler explanation draft.
- Make clear it is a retrieval fallback if model failed.

This makes the feature useful even if Hermes/Codex times out.

### Update query_passages signature

Update:

```python
query_passages(..., use_model: bool = False, model: str = DEFAULT_ANSWER_MODEL, action: str = DEFAULT_BOOK_CHAT_ACTION)
```

Behavior:

- normalize action
- retrieve passages as before
- if `use_model=True`, call `build_book_chat_prompt(question, hits, action=action)`
- pass selected model to `ask_via_hermes_codex`
- if gateway succeeds, return answer
- if gateway fails/empty, fallback to `_retrieval_only_answer(question, hits, action=action)`
- response JSON should include:
  - `action`
  - `model_provider`
  - `model`
  - `fallback_used`
  - existing citations and retrieved passages

Keep `DEFAULT_ANSWER_MODEL = "gpt-5.5"`.

## HTTP endpoint changes

In `monitor_server.py` POST `/api/library/book-chat/query`:

- parse `action = body.get("action")`
- parse `model = body.get("model")` if string else default
- parse `use_model`
- important: for this slice, if `use_model` is missing, default to **true** for normal UI queries, so the real answer mode is used. To preserve tests/backcompat, allow explicit `use_model: false` to force retrieval-only.

Suggested parsing:

```python
use_model = body.get("use_model")
if use_model is None:
    use_model = True
else:
    use_model = bool(use_model)
```

Pass `action=action` and `model=model` to `query_passages`.

## Frontend changes

In `dashboard/index.html`:

### Track selected quick action

Add state field if needed:

```js
state.bookChatAction = 'answer'
```

Quick action behavior:

- When quick action button is tapped, set `state.bookChatAction = action`.
- Still optionally insert a helpful prefix into the textarea, but backend must receive the explicit action.
- Consider updating status/subtitle/placeholder so user sees selected mode.

### Query POST body

Update `sendBookChatQuery()` body to include:

```js
{
  book_id: id,
  question,
  action: state.bookChatAction || 'answer',
  use_model: true,
  model: 'gpt-5.5'
}
```

### Loading/status copy

Because real GPT-5.5 calls can take longer, change status from:

```text
Searching indexed passages…
```

to something like:

```text
Reading passages and asking GPT-5.5…
```

If response has `fallback_used`, show:

```text
Answer ready (retrieval fallback)
```

Otherwise show:

```text
GPT-5.5 answer ready
```

### Reset action

When opening Book Chat screen, reset action to `answer` unless user chooses a quick action.

## Tests to add/update

Use TDD.

### `tests/test_book_chat_service.py`

Add tests for:

1. `normalize_answer_action` returns valid values and defaults unknown to `answer`.
2. `build_book_chat_prompt(..., action="socratic")` contains Socratic instructions, passage ids, and no-invention grounding language.
3. `build_book_chat_prompt(..., action="practice")` contains practice instructions and citations requirement.
4. `query_passages(..., use_model=True, action="socratic")` calls the gateway with a prompt containing Socratic instructions and returns gateway text. Monkeypatch `book_chat.service.ask_via_hermes_codex` to avoid real LLM.
5. `query_passages(..., use_model=True, action="challenge")` falls back to action-aware retrieval answer if gateway fails.

### `tests/test_monitor_server_book_chat_api.py`

Add/update tests for POST `/query`:

- request with `{action:"socratic", use_model:false}` returns `action:"socratic"` in JSON.
- request without `use_model` defaults to model mode. Avoid real LLM by monkeypatching service gateway or handler embedder as existing tests do. If test structure makes this hard, at least test parser path with explicit `use_model:false` and service tests cover model default.
- request with `model:"gpt-5.5"` passes model to service if feasible.

### `tests/test_dashboard_reader_and_settings_shell.py`

Assert HTML/JS contains:

- `bookChatAction`
- `use_model: true`
- `model: 'gpt-5.5'` or equivalent
- `action: state.bookChatAction`
- `GPT-5.5` status copy

## Verification commands

Run:

```bash
./venv/bin/python -m pytest tests/test_book_chat_service.py tests/test_monitor_server_book_chat_api.py tests/test_dashboard_reader_and_settings_shell.py -q
./venv/bin/python -m pytest tests/ -q
```

Then live smoke after Hermes verifies:

- Against already-indexed `Influence Without Authority` book_id `68789d92-2b98-4d7c-a29c-4d5310e61765` on port 8123 or a test server.
- POST `/api/library/book-chat/query` with:

```json
{
  "book_id": "68789d92-2b98-4d7c-a29c-4d5310e61765",
  "question": "dealing with difficult and lazy coworkers",
  "action": "socratic",
  "use_model": true,
  "model": "gpt-5.5",
  "top_k": 3
}
```

Acceptable live smoke result:

- HTTP 200
- JSON has `action: "socratic"`
- `fallback_used` may be true if gateway times out, but the answer should contain actual question marks and Socratic-style questions.
- If gateway succeeds, `model_provider` should be `hermes_openai_codex`.

## Constraints

- Keep changes focused.
- Do not use Composer 2.5 Fast. Use `composer-2.5` regular/non-fast.
- Do not commit temporary helper scripts.
- Preserve retrieval-only mode for explicit `use_model:false`.
- Preserve citations in response JSON.
- Do not break existing indexing/progress work.
