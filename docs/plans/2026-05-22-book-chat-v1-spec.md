# Book Chat v1 Product + Technical Spec

> **For Hermes:** Use `subagent-driven-development` skill to implement this plan task-by-task when Philip is ready to build.

**Goal:** Add a text-only, semantically aware **interactive learning companion** to the audiobook app so Philip can talk with a selected book, apply its ideas to real personal/work problems, reinforce learning through dialogue, and receive grounded answers with cited passages, book-specific memory, and optional author-voice responses.

**Architecture:** Treat each imported book as a searchable knowledge object plus a reflective conversation space. During ingestion, extract and chunk EPUB text into stable passage records, embed those records for semantic retrieval, and answer chat questions through a grounded RAG pipeline. The chat UI lives inside the book detail/reader experience and supports citations, saved insights, book-specific memory, learning prompts, and links back to reader locations and, later, audio timestamps.

**Tech Stack:** Existing Python `monitor_server.py` backend, static `dashboard/index.html` frontend, local JSON/file-backed book metadata initially, SQLite or JSONL index for v1, **local embeddings with `BAAI/bge-base-en-v1.5`**, and **GPT-5.5 for answer generation via Hermes as a local model gateway using the existing OpenAI Codex OAuth credential**. Available Codex OAuth picker options currently include `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.3-codex`, `gpt-5.2`, and `gpt-5.3-codex-spark`; `gpt-4.1` is not exposed there. Fallback route: **Gemini API** through an app-side API-key provider if Hermes/Codex OAuth is unavailable, rate-limited, or brittle for this use case. Keep provider/model names configurable so embeddings and chat models can be swapped later.

---

## Product concept

Philip wants to “talk to his books,” but the deeper product goal is not trivia Q&A. The app should help him **interact with the medium** so he can understand, remember, and apply what he reads/listens to.

The first version should be text-only and focused on excellent semantic awareness, personal reflection, and learning reinforcement — not voice interaction.

The assistant should help with:

- asking what the book says about an idea
- asking for explanation of hard passages
- bouncing life/work/family/personal problems against the book’s ideas
- finding relevant passages even when the user does not know the exact words
- being challenged by the book’s perspective
- turning ideas into reflective questions, practices, or next steps
- optionally answering in an author-inspired voice
- remembering the user’s prior conversations and saved insights with that book

The feature should feel like a **reflective reading companion** built into the reader/player, not a generic chatbot. Its job is to help the book “work on the user” through dialogue while staying honest about what the text does and does not actually say.

---

## V1 scope

### In scope

1. **Per-book chat**
   - User opens a book and taps a Chat / Ask button.
   - Chat context is primarily the currently selected book.
   - The user can ask free-form questions.

2. **Strong semantic retrieval**
   - Search by meaning, not just keywords.
   - Retrieve relevant chunks/passages from the book.
   - Include chapter/section metadata in results.

3. **Grounded answers with citations**
   - Answers should quote or summarize relevant passages.
   - Each answer should include citations where possible:
     - chapter title/index
     - passage/chunk ID
     - short quote/snippet
     - “Open passage” link target

4. **Book-guided personal reflection**
   - User can describe a personal/work/family problem in normal language.
   - The assistant retrieves relevant passages and applies them carefully.
   - Responses separate:
     - `What the book says`
     - `How this may connect to your situation`
     - `Questions worth asking yourself`
     - `One small next step`
   - The assistant should be kind, concrete, and willing to challenge when the book’s ideas imply a hard truth.

5. **Learning reinforcement**
   - Offer follow-up actions such as:
     - `Explain this another way`
     - `Ask me Socratic questions`
     - `Challenge my assumptions`
     - `Give me a real-life example`
     - `Turn this into a practice exercise`
     - `Save this insight`

6. **Author-voice mode**
   - V1 may include an “Author voice” response style.
   - It must be clearly framed as “author-inspired from this book,” not literally the author speaking.
   - Author voice must remain grounded in retrieved passages.

7. **Memory**
   - Persist conversation history per book.
   - Store durable user reflections/insights per book when the user asks or when the interaction produces a useful saved insight.
   - Use memory in future chats with that same book.
   - Keep memory separate from raw chat logs.

8. **Text-only UI**
   - No speech input/output required in v1.
   - No live voice conversation required.

9. **Reader jump links**
   - Citation links should open the book reader near the cited passage when possible.
   - If exact paragraph navigation is not ready, chapter-level fallback is acceptable.

### Out of scope for v1

- Voice chat with the book.
- Multi-book comparison across the whole library.
- Sentence-perfect audio sync.
- Full “page number” fidelity for every EPUB.
- Automated voice cloning of the author.
- Unrestricted author impersonation.
- Default web/news/Wikipedia retrieval inside the main answer path.
- Cloud account sync.

---

## UX specification

### Entry points

Add a primary entry point on the book detail screen:

- Button label: `Ask this book`
- Secondary label/helper: `Chat with the text, find passages, and reflect with citations.`

Optional reader-mode entry:

- small icon/button in reader top bar: `Ask`
- opens chat with current reader location included as context.

### Chat screen layout

Mobile-first layout:

1. Header
   - back button
   - book title
   - mode selector: `Grounded` / `Author voice`

2. Message list
   - user messages
   - assistant messages
   - citations below assistant messages

3. Suggested starter prompts
   - `Summarize the main idea of this chapter`
   - `What does this book say about my situation?`
   - `Find passages about discipline`
   - `Challenge me from this book’s perspective`

4. Composer
   - multiline text input
   - send button

### Citation UI

Each citation card should show:

- Chapter: `Ch. 4 — The title`
- Snippet: short quote/excerpt
- Actions:
  - `Open passage`
  - `Bookmark insight`
  - later: `Play from here`

### Modes

#### Mode 1: Grounded

Default. Tone should be helpful, clear, and honest.

Behavior:

- Answer from retrieved passages.
- Say when the text does not clearly answer.
- Apply ideas carefully to the user’s problem.
- Include citations.

Example style:

> The book seems to frame this less as a motivation problem and more as a system problem. In Chapter 3, the author says…

#### Mode 2: Author voice

Optional v1 mode. Tone should approximate the voice and worldview of the book while staying grounded.

UI copy should say:

> Author voice is an interpretation based on this book’s text, not the literal author.

Behavior:

- Use first person only if product copy makes it clear this is a simulated/inspired voice.
- Do not fabricate new claims as if from the author.
- Include citations even in author voice.
- If the question is outside the book, answer with caveats.

Recommended prompt language:

> Respond in a voice inspired by the selected book’s style and ideas. Do not claim to literally be the author. Ground claims in the provided passages. If the passages do not support an answer, say so.

---

## Memory model

V1 needs two layers of memory.

### 1. Raw chat history

Purpose:

- Let the user reopen previous conversations.
- Provide short-term continuity.

Store:

- conversation ID
- book ID
- timestamps
- user message
- assistant message
- retrieved passage IDs
- selected mode

Retention:

- Keep locally unless user deletes.

### 2. Book-specific durable memory

Purpose:

- Remember what Philip has been working through with this book.
- Improve future conversations without replaying every old message.

Store as compact notes, for example:

```json
{
  "id": "mem_...",
  "book_id": "...",
  "type": "user_reflection|insight|preference|open_question",
  "text": "Philip connected Chapter 4's discussion of discipline with his struggle to maintain consistent gym habits.",
  "source_conversation_id": "...",
  "source_passage_ids": ["passage_..."],
  "created_at": "...",
  "updated_at": "..."
}
```

Memory rules:

- Do not store every random chat as memory.
- Ask before saving deeply personal reflections unless the user explicitly says to remember/save it.
- Store concise summaries, not long transcripts.
- Keep memory scoped to the book for v1.
- Later, promote selected memories to library-wide/user-wide memory.

V1 UI controls:

- `Save this insight`
- `View book memories`
- `Delete memory`

---

## Data model

### Book passage record

Each extracted passage/chunk should have a stable ID:

```json
{
  "id": "passage_<book_id>_<chapter_index>_<chunk_index>",
  "book_id": "...",
  "chapter_index": 4,
  "chapter_title": "The Chapter Title",
  "chunk_index": 12,
  "paragraph_index_start": 28,
  "paragraph_index_end": 31,
  "text": "...",
  "char_start": 12345,
  "char_end": 13920,
  "reader_target": {
    "type": "chapter_chunk",
    "chapter_index": 4,
    "chunk_index": 12
  },
  "audio_target": {
    "type": "chapter_or_abs_time",
    "chapter_index": 4,
    "abs_time_s": null,
    "confidence": "chapter_only"
  },
  "embedding_model": "...",
  "embedding": [0.0]
}
```

### Chat conversation record

```json
{
  "id": "chat_<uuid>",
  "book_id": "...",
  "title": "Question about discipline",
  "mode": "grounded|author_voice",
  "created_at": "...",
  "updated_at": "...",
  "messages": [
    {
      "role": "user",
      "content": "...",
      "created_at": "..."
    },
    {
      "role": "assistant",
      "content": "...",
      "citations": ["passage_..."],
      "created_at": "..."
    }
  ]
}
```

### Retrieval result record

```json
{
  "passage_id": "...",
  "score": 0.82,
  "match_type": "semantic|keyword|hybrid",
  "snippet": "...",
  "chapter_index": 4,
  "chapter_title": "..."
}
```

---

## Backend/API specification

### Indexing APIs

#### `POST /api/library/book-chat/index`

Request:

```json
{ "book_id": "...", "force": false }
```

Response:

```json
{
  "ok": true,
  "book_id": "...",
  "status": "indexed|already_indexed|started",
  "passage_count": 384,
  "embedding_model": "..."
}
```

#### `GET /api/library/book-chat/index-status?id=<book_id>`

Response:

```json
{
  "book_id": "...",
  "status": "missing|indexing|ready|error",
  "passage_count": 384,
  "updated_at": "...",
  "error": null
}
```

### Chat APIs

#### `POST /api/library/book-chat/query`

Request:

```json
{
  "book_id": "...",
  "conversation_id": null,
  "mode": "grounded",
  "message": "What does this book say about handling discouragement?",
  "reader_context": {
    "chapter_index": 4,
    "chunk_index": 12
  }
}
```

Response:

```json
{
  "conversation_id": "chat_...",
  "answer": "...",
  "citations": [
    {
      "passage_id": "passage_...",
      "chapter_index": 4,
      "chapter_title": "...",
      "snippet": "...",
      "reader_target": { "type": "chapter_chunk", "chapter_index": 4, "chunk_index": 12 },
      "audio_target": { "type": "chapter_or_abs_time", "chapter_index": 4, "abs_time_s": null, "confidence": "chapter_only" }
    }
  ],
  "memory_used": ["mem_..."],
  "suggested_memory": null
}
```

#### `GET /api/library/book-chat/conversations?book_id=<book_id>`

Lists prior conversations.

#### `GET /api/library/book-chat/conversation?id=<conversation_id>`

Loads one conversation.

### Memory APIs

#### `GET /api/library/book-chat/memory?book_id=<book_id>`

Lists book-specific memories.

#### `POST /api/library/book-chat/memory`

Create/update/delete memory entries.

Request examples:

```json
{ "action": "create", "book_id": "...", "text": "...", "type": "insight" }
```

```json
{ "action": "delete", "book_id": "...", "memory_id": "mem_..." }
```

---

## Retrieval design

### V1 retrieval algorithm

Use hybrid retrieval:

1. Normalize user query.
2. Embed query.
3. Retrieve top semantic matches from passage embeddings.
4. Retrieve keyword/BM25-ish matches from passage text.
5. Merge/rerank.
6. Prefer diversity across chapters unless the user asks about a specific chapter.
7. Add current reader chapter context if present.
8. Return top 4-8 passages to the LLM.

### Chunking strategy

Initial v1 chunking:

- chunk by chapter
- preserve paragraphs
- target 500-900 words per chunk
- overlap 1 paragraph or ~100 words
- keep paragraph indexes for citations

Avoid chunks that are too small; semantic retrieval improves with enough context.

### Embedding storage options

Acceptable v1 choices:

1. JSONL files per book
   - fastest to add
   - easy to inspect
   - okay for small libraries

2. SQLite with `sqlite-vec` or similar
   - better long-term
   - more setup

Recommendation:

- Start with JSONL + brute-force cosine search if library is small.
- Move to SQLite/vector index once feature proves valuable.

---

## Prompting design

### System behavior for grounded mode

The assistant receives:

- book metadata
- selected mode
- compact book memory
- recent conversation turns
- retrieved passages
- user question

Rules:

- Use the retrieved passages as primary source.
- Do not invent claims from the book.
- If the answer requires speculation, label it clearly.
- When applying to Philip’s personal situation, separate:
  - `What the book says`
  - `How it might apply`
  - `A practical next step`
- Include citation markers tied to passage IDs.

### System behavior for author voice mode

Rules:

- Voice/style may be inspired by the book.
- Claims must still be grounded in passages.
- Do not say “I, the author” unless UI copy and prompt clearly frame simulation.
- Prefer: “In this book’s voice…” or “A response in the book’s style might be…”
- Keep citations.

---

## Safety / trust rules

1. Never hide uncertainty.
2. Never imply the real author is actually responding.
3. For personal problems, the assistant may reflect and suggest next steps, but should not replace professional/legal/medical advice.
4. If retrieval confidence is low, say:
   - `I’m not finding a strong passage for that in this book yet.`
5. Use citations for substantial claims.
6. Avoid creating false quotes.

---

## Acceptance criteria

V1 is successful when:

- A book can be indexed into searchable passages.
- User can open one book and ask a natural-language question.
- The assistant retrieves semantically relevant passages.
- The response includes at least 1-3 useful citations when supported.
- Citation cards can open the relevant chapter/passage fallback.
- User can describe a personal problem and receive a structured book-guided reflection.
- Response structure clearly separates book claims, application, reflection questions, and next step.
- Learning follow-up actions are available after answers.
- Author voice mode exists and remains grounded.
- Book-specific chat history persists.
- User can save/delete at least one book-specific memory.
- Refreshing the app does not lose conversations or saved memories.

---

## Recommended implementation phases

### Phase 1: Indexable passages

- Extract EPUB text into chapter/paragraph/chunk records.
- Save passage records per book.
- Add index status to book detail UI.

### Phase 2: Semantic retrieval

- Add embeddings generation.
- Add local retrieval endpoint.
- Verify questions retrieve relevant passages.

### Phase 3: Grounded chat + reflection endpoint

- Add chat query endpoint.
- Store conversations.
- Return answer + citations.
- Add response-mode handling for:
  - direct book Q&A
  - explanation
  - book-guided personal reflection
- For personal reflection, structure answers into book claims, application, questions, and next step.

### Phase 4: Chat UI + learning actions

- Add `Ask this book` button.
- Add mobile chat screen/sheet.
- Render messages and citations.
- Add starter prompts for personal reflection and learning reinforcement.
- Add post-answer actions: explain another way, Socratic questions, challenge assumptions, real-life example, practice exercise, save insight.

### Phase 5: Author voice mode

- Add mode toggle.
- Add author-voice prompt.
- Keep citations and caveats.

### Phase 6: Memory

- Add save insight / memory APIs.
- Inject compact book memories into future chats.
- Add memory management UI.

### Phase 7: Reader/player linking polish

- Open reader at cited passage/chapter.
- Later map passage IDs to audio timestamps where chunk timing exists.

### Phase 8 / V1.5: Optional external author/background context

- Add explicit `Use author/background context` toggle.
- Cache external source records per author/book.
- Cite URLs and retrieval dates.
- Label source layers as `From this book`, `From author/background sources`, and `Assistant interpretation`.
- Keep book-only retrieval as the default.

---

## Personal reflection / learning-coach behavior

A major goal is not just factual Q&A. Philip wants to interact with the medium so he can understand and internalize it better.

The chat should support a **Book-guided reflection** workflow:

1. User explains a personal/work/family/problem situation in plain language.
2. The app retrieves relevant passages from the selected book.
3. The assistant separates the response into:
   - `What the book says`
   - `How this may apply to your situation`
   - `Questions to think through`
   - `A practical next step`
4. The assistant offers to save an insight/memory when the interaction reveals something durable.
5. Follow-up questions can continue from the same personal context.

This should feel more like a reflective reading companion than a generic advice bot.

### Reflection prompt requirements

- Stay grounded in retrieved passages.
- Clearly separate book-based interpretation from the assistant's own reasoning.
- Do not pretend the book has a direct answer if it does not.
- Be kind but willing to challenge Philip when the book's ideas imply a hard truth.
- Use short, concrete next steps instead of abstract encouragement.
- Preserve privacy by asking before saving sensitive memories.

Recommended answer structure for personal-problem questions:

```markdown
## What the book seems to say
[Grounded synthesis with citations]

## How it may connect to your situation
[Careful application; label assumptions]

## Questions worth asking yourself
[2-4 reflective questions]

## One small next step
[A practical action]

## Sources
[Citation cards]
```

### Learning reinforcement features

V1 should include optional prompts after an answer:

- `Explain this another way`
- `Ask me Socratic questions about this`
- `Give me a real-life example`
- `Challenge my assumptions`
- `Turn this into a practice exercise`
- `Save this insight`

These interactions make the book more memorable because the user actively works with the ideas.

---

## External author/context retrieval

External author information can be useful, but it should be a separate, clearly labeled context layer rather than mixed silently into the book's claims.

### Should v1 retrieve external author information?

Recommended default: **not in the first MVP answer path**. Start with book-grounded answers first.

Reason:

- The core magic is talking to the selected book.
- External info increases complexity and hallucination risk.
- News/Wikipedia/interviews can contaminate “what the book says.”
- Living authors and recent news introduce freshness and accuracy problems.

### When external info makes sense

Add as V1.5/V2 under an explicit toggle such as:

- `Use author/background context`
- `Search outside the book`
- `Include interviews/articles`

Useful cases:

- “What did the author mean by this?”
- “How does this idea fit the author’s broader work?”
- “Has the author talked about this in interviews?”
- “What criticism exists of this idea?”
- “What was happening historically when this was written?”

### Required source separation

The answer must label sources distinctly:

- `From this book`
- `From author/background sources`
- `Assistant interpretation`

Never present Wikipedia/news/interview material as if it came from the book.

### External source data model

```json
{
  "id": "author_source_...",
  "book_id": "...",
  "author": "...",
  "source_type": "wikipedia|interview|article|news|author_site|other_book",
  "title": "...",
  "url": "...",
  "published_at": "...",
  "retrieved_at": "...",
  "text": "...",
  "trust_level": "high|medium|low",
  "embedding": [0.0]
}
```

### External retrieval architecture

1. Build book-only retrieval first.
2. Add optional author/source corpus per author.
3. In query handling, retrieve from:
   - book passages
   - saved book memories
   - optional author/background sources
4. Rerank with source-type awareness.
5. Generate answer with strict source labels.

### External retrieval safety rules

- Default to book-only unless user enables external context.
- Cite URLs for external sources.
- Show retrieval date for dynamic sources like news.
- Prefer stable sources: official author sites, interviews, Wikipedia, publisher pages, academic pages.
- Treat news and random articles as lower-trust unless corroborated.
- Allow per-book/author external source cache so the app is not web-searching every chat.

---

## Chosen v1 infrastructure defaults

1. **Embedding provider/model:**
   - Local sentence-transformers using `BAAI/bge-base-en-v1.5`.
   - Store embedding model name, vector dimension, and text hash with every passage so the index can be rebuilt if the model changes.
   - Run embeddings locally to avoid uploading full book text and avoid per-book embedding API cost.

2. **Answer model:**
   - Use `gpt-5.5` for answer generation initially, since `gpt-4.1` is not currently exposed in the OpenAI Codex OAuth picker.
   - Current visible OpenAI Codex OAuth options: `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.3-codex`, `gpt-5.2`, `gpt-5.3-codex-spark`.
   - Primary route: call Hermes as a local model gateway so Hermes handles the existing OpenAI Codex OAuth credential, token refresh, and provider/model routing.
   - Fallback route: use Gemini API through an app-side API-key provider, preferably `gemini-2.5-pro` for high-quality reflective answers or `gemini-2.5-flash` for cheaper/faster fallback.
   - Keep the provider/model configurable so the app can later test Claude/Kimi/local alternatives.

3. **Storage:**
   - JSONL first for passage records, conversations, and memories.
   - SQLite remains the likely next step once the shape stabilizes.

4. **Author voice strictness:**
   - Default framing: “author-inspired from this book,” not literal author impersonation.
   - Keep citations required in author-voice mode.

5. **Memory confirmation:**
   - Ask before saving sensitive personal reflections by default.
   - Later allow opt-in auto-save per book.

---

## Recommended v1 defaults

- Use JSONL passage storage first.
- Use local `BAAI/bge-base-en-v1.5` embeddings.
- Use `gpt-5.5` through Hermes/OpenAI Codex OAuth for answer quality initially.
- Default mode: `Grounded`.
- Include `Author voice` as an explicit optional toggle.
- Ask before saving personal memories.
- Citation jump target: chapter/chunk first, audio timestamp later.

---

## Implementation prerequisites and execution plan

### Pre-flight checkpoint

- The audiobook folder must be protected by git before major changes.
- Exclude generated outputs, local libraries, imported books, venvs, and secrets from git.
- Commit a baseline before implementation and make additional commits after meaningful verified milestones.

### Required local packages

For local embeddings and retrieval smoke tests:

- `sentence-transformers`
- `scikit-learn`
- existing `torch`, `transformers`, `numpy`, and `requests`

Optional/likely packages for richer EPUB extraction later:

- `ebooklib`
- `beautifulsoup4`

### Spike gates before full build

1. **Embedding smoke test**
   - Load `BAAI/bge-base-en-v1.5` locally.
   - Embed several sample passages and one query.
   - Verify cosine similarity returns the expected passage.

2. **Hermes/Codex model-gateway proof-of-concept**
   - Add a small app-callable Python wrapper that shells out to Hermes for a plain non-agent completion.
   - Target `gpt-5.5` through OpenAI Codex OAuth first.
   - Return structured metadata: provider route, model, fallback used, raw text.
   - Keep it isolated from production chat code until verified.

3. **Gemini fallback proof**
   - If Hermes/Codex fails or is unavailable, verify a Gemini API fallback path can answer the same simple prompt.
   - Use the existing Gemini key from the local environment/Hermes `.env` for the personal app path.

4. **Cursor implementation phase**
   - Once the POC is good enough, use Cursor CLI as the code-change executor.
   - Use **Composer 2.5 regular / non-fast** as requested.
   - Hermes acts as orchestrator: prepare task briefs, run Cursor, inspect diffs, run tests, and re-prompt Cursor for fixes.
   - Do not let Cursor skip tests; preserve the baseline git checkpoint.

### Initial build slices for Cursor

1. Add model gateway abstraction and tests.
2. Add local BGE embedding/retrieval module and tests.
3. Add passage/chunk storage and indexing API.
4. Add grounded chat endpoint with citations and fallback metadata.
5. Add minimal mobile-first chat UI on book detail/reader.
6. Add memory save/list/delete behavior.
7. Add author-voice mode and learning-action buttons.

---

## Notes for future implementation

The current audiobook app already has useful foundations:

- book detail pages
- reader mode
- chapter timeline concepts
- bookmarks and notes
- persistent playback state
- per-book metadata

This feature should build on those instead of creating a separate app.

The major new capability is the text knowledge layer: stable passage IDs, embeddings, retrieval, and citation-aware answer generation.
