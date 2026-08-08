# RAGbase — Codebase Explained

Welcome. This is the document I'd give you on your first day: not a list of what the
files are, but an argument for why the system is shaped this way, what happens when you
press Enter, and which parts you should not trust yet.

Read `.ai/instructions.md` alongside this. That file is the reference — conventions,
exact endpoint signatures, the gotcha list. This file is the narrative.

Verified against the source on 2026-08-07.

---

## Table of contents

1. [What RAGbase is](#1-what-ragbase-is)
2. [How a query works, end to end](#2-how-a-query-works-end-to-end)
3. [How ingestion works, end to end](#3-how-ingestion-works-end-to-end)
4. [The data flow](#4-the-data-flow)
5. [Module by module](#5-module-by-module)
6. [Architecture decisions](#6-architecture-decisions)
7. [Known tradeoffs and rough edges](#7-known-tradeoffs-and-rough-edges)

---

## 1. What RAGbase is

**The problem.** You accumulate knowledge in incompatible formats. Lecture notes as
handwritten PDFs. Textbook chapters as typed PDFs. Whiteboard photos. Recorded lectures.
YouTube explainers. Each lives in a different app, none of them talk, and none can
answer "what did I actually learn about X?" Search is per-app and keyword-only, so you
have to remember *where* something was before you can find *what* it said.

**What this does.** Ingest all of it into one place, then ask questions in natural
language and get answers grounded in your own material, with citations back to the
source chunks.

**Who it's for.** One person, on their own machine, with their own documents. That
single assumption drives nearly everything below: there is no multi-tenancy to design
around, no horizontal scaling, no auth. There *is* a `user_id`, and every collection and
graph table is namespaced by it — but it is generated once on first launch and there is
exactly one. It's isolation-by-construction for a future that may never come, and it
costs almost nothing to keep.

**Why local-first.** Three reasons, in order of how much they mattered:

1. **Privacy.** Personal notes are personal. The moment you send them to a hosted API
   you've made a permanent decision about someone else's copy of your data. Running
   locally makes that decision unnecessary rather than merely well-managed.
2. **Cost.** Ingesting a few hundred PDFs through a hosted model is a real bill, and it
   recurs every time you re-ingest. Locally it's electricity.
3. **It works offline**, which for a personal knowledge base is closer to a requirement
   than a nice-to-have.

The cost of that choice is the constraint everything else bends around: **you get one
M3 Mac's worth of compute, and one Ollama process at a time.** Nearly every design
decision in section 6 traces back to that sentence.

**What runs where.** All compute is on the Mac: Ollama, ingestion, the FastAPI backend,
ChromaDB (embedded, in-process), SQLite. A Raspberry Pi 5 on Tailscale receives
anonymous telemetry and nothing else — it runs zero AI compute and zero RAG logic, and
if it's unreachable the app doesn't notice. The Next.js frontend runs on localhost and
talks to FastAPI on port 8001.

---

## 2. How a query works, end to end

You type "What is the CIA triad?" and press Enter. Here is every layer it touches.

### 2.1 The frontend decides which endpoint to call

`app/page.tsx` owns the source selection state, and one line decides the mode:

```ts
const isDirectMode = selectedSources.size === 0;
```

Deselecting every source doesn't mean "search nothing" — it means "don't search at all."
That routes to `/query/direct`, which skips retrieval entirely and is dramatically
faster. If a *strict subset* is selected, that array is sent as `source_filter`. If
everything is selected, `null` is sent, meaning "no restriction." An empty array is
never sent, because to the backend that would mean "restrict to nothing."

`useChat.sendMessage()` then does something subtle before anything else:

```ts
if (isLoadingRef.current) {
  abortRef.current?.abort();
  await new Promise((resolve) => setTimeout(resolve, 100));
  isLoadingRef.current = false;
}
```

If a stream is already open, it's aborted and we wait 100ms. Without that pause the
previous fetch's reader throws mid-teardown. It looks like a hack because it is one, but
it's a load-bearing one.

It also increments a `generationRef` counter and captures it. The `finally` block only
clears loading state if `generationRef.current === gen` — so a stream that gets
superseded can't stomp the state of the one that replaced it.

Then it pushes two messages into the session: your message, and an **empty assistant
message**. Tokens will stream into that second one by id. This is why the UI can show a
response materializing rather than appearing all at once.

### 2.2 Auto-compaction, if needed

Before sending, if the session has more than 10 messages *and* the estimated token count
is ≥ 90% of qwen3's 40,960 limit, everything except the last 10 messages is sent to
`POST /compact`, summarized by qwen2.5:3b, and replaced with a single system message.
The estimate is deliberately crude — `chars/4 + 1500 per exchange` — because the
1500-per-exchange term is standing in for retrieved context we never counted precisely.
Being roughly right early beats being exactly right too late. If compaction fails, it's
swallowed and the turn proceeds.

### 2.3 The request arrives: `POST /query/stream`

`api/query.py::query_stream` returns a `StreamingResponse` wrapping an async generator.
Everything below happens *inside* that generator, which is why progress can be reported
as it goes.

**Stage 0 — the cache check.** Unless a `source_filter` is set, the question is embedded
and checked against the semantic cache (cosine ≥ 0.85, 24h TTL). On a hit, stages 1-4 are
skipped entirely and the generator jumps straight to generation — so the stage sequence
the client sees is `retrieving_sources` → `generating`, with no `traversing_graph` or
`reranking` events. Only the *retrieval context* is reused; the answer is always
regenerated against the exact wording asked.

Source-filtered queries bypass the cache in both directions: the cached context was built
under a different filter, so reusing it would surface chunks from sources the user
deliberately deselected.

### 2.4 Stage 1 — which documents are even relevant?

```python
yield f"data: [STAGE]{json.dumps({'stage': 'retrieving_sources'})}\n\n"
```

The first thing the user sees is "Retrieving sources…". Then `search_summaries()` runs.

This is **hierarchical retrieval**, and it's the least obvious part of the pipeline.
Instead of searching all chunks immediately, we first search a *separate collection*
containing one LLM-written summary per document. The question is embedded and matched
against those summaries to decide which documents are worth looking inside.

```python
n_results = min(max(3, total_sources // 3), 8)
```

The count scales with library size: with 3 documents it returns 3 (searching everything
is fine and over-filtering would be harmful); with 90 it returns 8. Anything with cosine
distance above `0.7` is dropped as off-topic — but if *everything* exceeds the
threshold, it falls back to the unfiltered list rather than returning nothing. A weak
match beats no answer.

Why bother? With 10 documents it's overhead. With 500 it's the difference between
searching 50,000 chunks and searching 800. It's built for the library this becomes, not
the one it starts as.

### 2.5 Stage 2 — knowledge graph augmentation

Only if `has_graph(user_id)` returns true — a single indexed `SELECT 1 ... LIMIT 1`, so
users who've never finished a graph build pay nothing.

`query_related_sources()` extracts words longer than two characters from the question,
finds graph nodes whose entity text contains any of them, and runs a NetworkX BFS out to
2 hops. Every node reached contributes the source it came from.

The point is **recall on questions whose wording doesn't match the document's wording**.
If one document says "confidentiality, integrity, availability" and another says "CIA
triad," embeddings may not connect them, but the graph might — because both mention
entities that link. Those extra sources are unioned with Stage 1's.

Two hops is a judgement call. One hop is barely more than keyword matching; three starts
pulling in most of a well-connected graph.

### 2.6 Stage 3 — hybrid chunk retrieval

Now `search()` looks inside the chosen documents. It does two searches and fuses them.

**Vector search** fetches `TOP_K_CANDIDATES` (20) chunks by cosine similarity, capped at
the collection size because Chroma errors if you ask for more rows than exist.

**BM25 keyword search** then re-scores **only those 20 candidates** — not the corpus:

```python
tokenized = [doc.lower().split() for doc in docs]
bm25 = BM25Okapi(tokenized)
bm25_scores = bm25.get_scores(query.lower().split())
```

That's a real approximation, and worth being honest about. A pure-BM25 search over the
whole corpus could surface a chunk that vector search missed entirely; this design can't
— it can only *reorder* what vector search already found. In exchange it costs nothing
(no corpus-wide index to build or maintain) and still recovers most of the benefit,
which is fixing the ordering when an exact term matters.

Why have BM25 at all? Embeddings are bad at exact tokens. Error codes, function names,
proper nouns, `RERANKER_MIN_SCORE` — these get smeared into semantic neighborhoods.
Keyword search nails them.

**Reciprocal Rank Fusion** then merges the two rankings:

```python
scores[idx] += 1 / (k + rank + 1)     # k = 60
```

RRF uses only **rank**, never the underlying scores. That's the whole trick. Cosine
distances and BM25 scores live on incomparable scales, so blending them directly needs
per-corpus weight tuning that would silently rot. Rank is unitless and comparable by
construction. `k=60` is the value from the original RRF paper; it damps the influence of
top ranks enough that one list can't dominate.

Top 5 by fused score go forward.

### 2.7 Stage 4 — cross-encoder reranking

```python
yield f"data: [STAGE]{json.dumps({'stage': 'reranking'})}\n\n"
```

Everything so far used a **bi-encoder**: the question and each chunk were embedded
*independently* and compared. That's what makes retrieval fast — chunk vectors are
precomputed — but it means the model never sees the question and the chunk together.

`BAAI/bge-reranker-v2-m3` is a **cross-encoder**. It takes `(question, chunk)` as a
single input and outputs one relevance score, so it can model interactions a dot product
cannot. It's far more accurate and far more expensive — which is exactly why it runs on
~20 candidates rather than the corpus. This ordering (cheap and broad, then expensive
and narrow) is the standard shape of a good retrieval pipeline.

All pairs go through in **one batched forward pass**. There's a per-item fallback if the
batch throws, and if the model won't load at all, `rerank()` returns the original order
with dummy scores of 1.0 rather than failing the query.

**The scores are raw, unbounded logits — roughly -10 to +8 — not probabilities.** This
matters constantly. They can't be softmaxed. They can't be shown as percentages without
normalization (the frontend applies a sigmoid in `relevancePercent`). Their absolute
values aren't calibrated across questions; only relative ordering is meaningful.

### 2.8 Stage 5 — the threshold, and the fallback

Anything below `RERANKER_MIN_SCORE = -8.0` is dropped. If nothing survives:

```python
logger.info("No chunks above threshold — LLM will answer from own knowledge")
docs, metas, scores = [], [], []
```

The query proceeds with **empty context**. The model answers from its own knowledge, no
retry, no refusal. This is a deliberate product decision: a useful answer beats "I don't
know," and because the response carries zero citations, the UI shows no "Sources used"
button — so you can always tell the difference between grounded and ungrounded.

### 2.9 Stage 6 — generation and streaming

`build_context()` numbers the chunks with their source names, `build_answer_prompt()`
assembles the final prompt, and then:

```python
for token in generate_stream(prompt, system=_SYSTEM_PROMPT, model=get_model("answer")):
    if token:
        yield _sse_token(token)
```

Three details, each of which has caused a bug:

**`if token:`** — qwen3 is a thinking model, and Ollama streams chunks with empty
`content` while it reasons. Without this filter roughly 80% of frames carry nothing.

**`_sse_token()` JSON-encodes the token.** SSE frames are delimited by a blank line, so a
raw `\n` inside `data: {token}\n\n` collides with the delimiter — the token gets split
across frames and its newline vanishes. Before this was fixed, *every* markdown list,
heading and paragraph in every answer collapsed onto one line. JSON escapes newlines to
literal `\n`, so whitespace survives. Control frames keep bare `[MARKER]` prefixes, so a
payload starting with `"` is unambiguously a token.

**`_SYSTEM_PROMPT`** is aggressively anti-narration: never cite source names inline,
never say "the context" or "the provided documents," weave everything in as if already
known. Qwen3 will otherwise produce "Based on the provided context, document 3
states…", which is exactly what a citation UI is for.

Before generation, `await request.is_disconnected()` is checked. Clicking Stop actually
halts backend work rather than just hiding the output.

Finally `[SOURCES]` carries the citations, then `[DONE]`.

### 2.10 Back on the client

`consumeQueryStream()` in `lib/api.ts` is the only SSE parser, shared by all three
streaming calls. Its subtleties:

```ts
const frames = buffer.split("\n\n");
buffer = frames.pop() ?? "";     // last element may be a partial frame
```

Network chunks don't align to frame boundaries, so the trailing fragment is always held
back for the next read.

```ts
const line = frame.replace(/^\n+/, "").replace(/\r$/, "");
```

**Only the framing is stripped — never the payload.** An earlier `frame.trim()` deleted
whitespace-only tokens outright, producing text like `"12 multiplied by8 equals96"`.

And an easy one to get wrong: `reader.cancel()` resolves the pending `read()` with
`done: true` rather than rejecting, so an abort has to be detected via `signal.aborted`
and re-thrown as an `AbortError`, or the caller's abort handling silently never runs.

Each token appends to the assistant message by id; React re-renders; `MessageBubble`
runs it through ReactMarkdown with KaTeX. On `[DONE]` the message is marked complete and
the citations render.

**Total: ~2-25 seconds**, dominated by qwen3 generation. Retrieval is typically under a
second.

---

## 3. How ingestion works, end to end

You drag `lecture_notes.pdf` onto the drop zone.

### 3.1 Upload returns immediately

`POST /ingest/file` saves the original to `data/sources/{user_id}/{source}.pdf` (so it
can be previewed later), writes the bytes to a temp file, appends a job record with
status `"queued"`, and **returns a `job_id` right away**. The HTTP request is over in
milliseconds; nothing is processed yet.

The queue does two things worth noting. It refuses to enqueue a source that already has
an active job, returning the existing `job_id` instead — double-clicking upload can't
start two ingestions. And it estimates a duration (`max(5, size_mb * 1.5)` for PDFs, a
flat 15s for images) purely so the frontend's progress bar has something to animate
against. It's a UI affordance, not a real prediction.

### 3.2 The worker picks it up — Phase 1

A single background thread processes one job at a time. Ingestors are imported *inside*
the branch that needs them, so `docling`, `paddleocr`, `whisper` and `yt-dlp` — all
heavy — only load when a job of that type actually runs. Server startup stays fast.

Status flips to `"ingesting"` and `BaseIngestor.ingest()` runs. This is the template
method at the heart of ingestion: **subclasses implement `extract_text()` and nothing
else.** Chunking, embedding, storage, summarization and graph enqueueing are all
inherited, so adding a new format means writing one method.

**Extraction** (the format-specific part) is covered in §5.

**Re-ingestion cleanup.** If ChromaDB already has chunks for this source name,
`delete_source()` wipes chunks, summary, graph data and cache first. This is skipped for
brand-new sources so the graph DELETE path isn't exercised needlessly.

**Chunking** splits on **words, not tokens**: 512 words with 50 words of overlap. Words
are a proxy for tokens (roughly 0.75 words per token for English), chosen because it
needs no tokenizer and no model-specific dependency. The overlap exists so a sentence
spanning a boundary still appears whole in one of the two chunks — without it, the
chunk boundary becomes a blind spot.

**Storage** embeds in batches of 64 via bge-m3 and writes to `user_{user_id}`. Failures
degrade rather than abort: a failed batch logs and inserts `None` placeholders, and
chunks with no embedding are skipped individually. Losing one chunk of a 200-chunk
document is much better than losing the document.

**Summarization** takes the first 2000 characters, asks qwen2.5:3b for a 3-4 sentence
summary, and stores it in `user_{user_id}_summaries`. That's the Stage 1 index from §2.4
being built. First 2000 chars only — a real summary of the full text would cost far more
and mostly restate the introduction anyway.

Then: status `"ingested"`, `clear_cache(user_id)`, telemetry.

**At this moment the source is fully queryable.** This is the single most important
thing to know about ingestion. `"done"` comes later and only adds the graph.

### 3.3 Phase 2 — the knowledge graph

```python
enqueue_graph_build(self.job_id, partial(self._build_graph_background, chunks, source_name))
```

The job is marked `"waiting_for_graph"` and a callback goes onto a **second, separate
queue** with its own worker thread.

The graph build runs `extract_entities()` on **every chunk** — one LLM call each. For a
200-chunk document that's 200 sequential calls, minutes of work. That's the entire
reason for the two-phase split: this is slow, and it only *improves* recall rather than
enabling it.

Extraction asks qwen2.5:3b for JSON, then defends heavily against the result:
`_strip_latex()` first (malformed LaTeX reliably breaks JSON generation), then
`repair_json()` before `json.loads()`, then `_validate_extracted()` drops entities under
3 characters, stop words, numeric-only strings, LaTeX fragments, and case-insensitive
duplicates. Small models produce a lot of garbage; every one of those filters exists
because something bad got through.

Rows go in with `INSERT OR IGNORE`, which gives no signal about whether it inserted, so
counting compares `conn.total_changes` before and after.

Status becomes `"done"`.

### 3.4 Why two queues, not one

Both queues are single-worker, but they are **independent**. If graph builds shared the
ingestion queue, a slow graph build would block the next document's Phase 1 — destroying
the benefit of deferring it. If graph builds instead ran as unbounded threads, ingesting
five documents would launch five concurrent entity-extraction runs against one local
Ollama process; measured, that was *slower* than doing them one at a time.

Two independent sequential queues is the shape that makes both properties true: new
documents become queryable fast, and graph builds never contend.

### 3.5 Cancellation

Cancellation is **cooperative**. `cancel_job()` only flips a status; ingestors call
`is_cancelled()` at the top of each chunk batch and each page loop and raise
`IngestionCancelled`. A job sitting inside a single 90-second VLM call keeps running
until that call returns — there's no way to interrupt a blocking library call safely.

### 3.6 Crash recovery

On startup, any job left in an active status is reset to `"queued"` and re-enqueued —
but only if its record still has `source`, `user_id` and `tmp_path`. Otherwise it's
dropped with a warning, because the temp file is gone and there's nothing to reprocess.
The status file is always written atomically (temp file + `os.replace`), so a crash
mid-write can't corrupt it.

---

## 4. The data flow

```
  raw file (PDF / image / video / URL / text)
        │
        │  data/sources/{user_id}/{source}{ext}      ← original, kept for preview
        ▼
  extract_text()                                    ← format-specific; the only
        │                                             thing subclasses implement
        ▼
  plain text
        │
        ├──────────────► summary (qwen2.5:3b, first 2000 chars)
        │                      │  embed (bge-m3)
        │                      ▼
        │                user_{id}_summaries  ──────────────┐
        │                                                    │  Stage 1:
        ▼                                                    │  which docs?
  chunk_text()  512 words / 50 overlap                       │
        │                                                    │
        │  embed_batch (bge-m3, 64 at a time)                │
        ▼                                                    │
  user_{id}  (ChromaDB, cosine HNSW)  ─────────────────┐     │
        │                                              │     │  Stage 3:
        │  [Phase 2, deferred]                         │     │  which chunks?
        ▼                                              │     │
  extract_entities() per chunk (qwen2.5:3b)            │     │
        │                                              │     │
        ▼                                              │     │
  nodes_{id} / edges_{id}  (SQLite, WAL) ──────────┐   │     │
                                                    │   │     │
                                        Stage 2:    │   │     │
                                        related docs│   │     │
                                                    ▼   ▼     ▼
                                              ┌─────────────────────┐
                            question ────────►│  RAGPipeline        │
                                              │  1 summaries        │
                                              │  2 graph (optional) │
                                              │  3 BM25+vector RRF  │
                                              │  4 cross-encoder    │
                                              │  5 threshold        │
                                              └──────────┬──────────┘
                                                         │ context
                                                         ▼
                                            generate_stream (qwen3)
                                                         │
                                                         ▼
                                              SSE  ──►  browser

  data/cache.db  ← written/read ONLY by POST /query, which the UI never calls (§7)
```

Three storage systems, three different jobs:

- **ChromaDB** — dense vectors and chunk text. Two collections per user: chunks and
  summaries. Cosine HNSW.
- **SQLite (knowledge_graph.db)** — entities and relationships, per-user tables, WAL.
- **SQLite (cache.db)** — query-embedding-keyed retrieval context, WAL. Currently
  unreachable from the UI.

---

## 5. Module by module

### `main.py`

**What it does:** Creates the FastAPI app, wires routers and CORS, and runs startup in a
lifespan context manager.

**Why it exists:** Single composition root — the one place that knows about every
subsystem.

**Non-obvious behavior:** Warmup is **non-blocking**. `configure_dspy()` and both queue
workers start synchronously, but reranker and model warmups are launched with
`asyncio.create_task()` and *not* awaited. "RAGbase ready" is logged before warmup
finishes, so the first query right after startup can still be slow. This is deliberate:
the server accepts requests immediately instead of blocking ~30s on model loads.

**Design decisions:** CORS allows `localhost:3000` explicitly *plus* a regex for any
localhost port, because the Next.js dev server falls back to another port when 3000 is
taken. Must be tightened for any non-local deployment.

---

### `config/settings.py`

**What it does:** Every tunable constant in the project.

**Why it exists:** So no magic numbers live in application code, and so tuning retrieval
means editing one file.

**Design decisions:** **No `.env`, no environment variables.** For a single-user local
app, env vars add a failure mode (works on my machine, breaks on yours) and buy nothing —
there are no secrets and no per-environment differences. Runtime-mutable settings
(telemetry, display name) live in `data/settings.json` instead, because those are user
preferences rather than configuration.

Values worth knowing: `CHUNK_SIZE=512` words, `CHUNK_OVERLAP=50`, `TOP_K_CANDIDATES=20`,
`MAX_FINAL_RESULTS=5`, `RERANKER_MIN_SCORE=-8.0`, `SUMMARY_DISTANCE_THRESHOLD=0.7`,
`RRF_K=60`, `CACHE_SIMILARITY_THRESHOLD=0.85`, `CACHE_TTL=86400`.

---

### `config/models.py`

**What it does:** `get_model(task)` maps a semantic task name to a model name.

**Why it exists:** It is the **only** place a model name string appears. Swapping the
fast model everywhere is a one-line change.

**Non-obvious behavior:** Raises `ValueError` on an unknown key rather than defaulting —
a typo fails loudly instead of silently routing to the wrong model.

**Design decisions:** Keys are **semantic, not physical**. `entity_extraction` and
`summarize` both resolve to `qwen2.5:3b` today, and `vision_handwrite`,
`vision_diagram` and `vision_simple` all resolve to `qwen2.5vl`. Keeping them distinct
means routing can diverge later without touching a single call site. `query_rewrite` and
`vision_diagram` are currently unreferenced — kept for the same reason.

---

### `config/paths.py` · `config/logging.py` · `config/runtime.py`

`paths.py` centralizes every filesystem path. Note `KNOWLEDGE_GRAPH_DB_PATH` is
`data/knowledge_graph.db`, and `RERANKER_MODEL_PATH` is **never loaded by anything** —
the reranker always pulls the base checkpoint from HuggingFace. `reset_all.sh` deletes
that path defensively in case a fine-tuned checkpoint is ever dropped there.

`logging.py::setup_logging(name)` returns a logger with a console handler at INFO and a
per-module file handler at DEBUG. It guards on `logger.handlers` so repeated calls don't
duplicate output.

`runtime.py` holds identity and mutable settings. `USER_ID` and `DEVICE_ID` are generated
with `secrets.token_hex(4)` on first launch and persisted. **They are load-bearing**:
every ChromaDB collection name and every graph table name embeds `USER_ID`, so changing
that file orphans the entire corpus. `DEVICE_ID` is separate specifically so telemetry
never carries the ID that identifies the user's data. Settings writes are atomic.

---

### `ingestion/base.py`

**What it does:** `BaseIngestor` — the template method that owns the whole two-phase
pipeline.

**Why it exists:** Without it, every format would reimplement chunking, batched
embedding, error handling, status transitions, summarization and graph enqueueing. It
turns "support a new format" into "write one method."

**Non-obvious behavior:** The document summary passes an explicit
`model=get_model("summarize")`. Omitting it would silently run on qwen3 — the default —
which would be several times slower for no benefit.

**Key functions:**
- `ingest()` — the Phase 1 sequence, plus the Phase 2 enqueue
- `store()` — batched embed + add, with per-chunk failure isolation
- `store_summary()` — writes the Stage 1 index entry
- `_build_graph_background()` — Phase 2 callback, runs on the graph queue

**Design decisions:** Cancellation is checked at the top of each **batch**, not each
chunk — checking per chunk would read the status file 200 times per document.

---

### `ingestion/queue.py`

**What it does:** Two independent single-worker queues, plus a JSON status file.

**Why it exists:** Ingestion must survive the HTTP request that started it, and must be
observable afterward.

**Non-obvious behavior:** State lives in a **file**, not memory, so status survives
restarts and the reconciliation logic can re-enqueue interrupted jobs. All writes are
atomic. Error statuses are the literal string `"error: <detail>"` and are detected with
`.startswith("error")` — stringly-typed, but it means the detail rides along to the UI
for free.

**Key functions:** `enqueue()` / `enqueue_url()` / `enqueue_text()` (all with duplicate
guards), `start()` (also runs reconciliation), `start_graph_queue()`,
`enqueue_graph_build()`, `cancel_job()` / `is_cancelled()`, `clear_completed()`.

**Design decisions:** `clear_completed()` only sweeps the **status file** — it never
touches ChromaDB or the graph. Clearing the display must never destroy data.

---

### `ingestion/pdf.py`

**What it does:** The most complex ingestor. Branches between typed and handwritten PDFs.

**Non-obvious behavior:** Handwriting detection is a **heuristic on Docling's markdown
output** — more than 5 `<!-- image -->` markers with under 200 characters of real text,
or fewer than 50 characters of text per image. A PDF that is mostly scanned images looks,
to Docling, like image placeholders and nothing else. That's the signal.

Handwritten extraction converts each page to PNG and sends it to qwen2.5vl, then runs a
DSPy `TranscriptionRefinement` pass to strip narration — VLMs habitually describe math
("the equation shows the sum of...") instead of transcribing it. Each page gets 3
attempts with escalating timeouts, and **progress is written to
`data/{source}_progress.json` after every page**, so a 60-page document interrupted at
page 40 resumes at 41 instead of restarting.

Typed extraction iterates `doc.texts` and groups by `prov[0].page_no`. It does *not* use
`doc.export_to_markdown(page_no=N)`, which is unreliable, and `doc.pages` contains no
text at all. Each page runs through a `TextCleanup` DSPy pass individually, so one page's
cleanup failing falls back to that page's raw text rather than losing the document.

**Embedded images require explicit pipeline options.** The converter sets
`generate_picture_images=True` (without it `PictureItem.get_image()` is `None` for every
picture) and pins `ocr_options=RapidOcrOptions()` (Docling's default `"auto"` resolves to
whatever engine happens to be installed). `_describe_images()` returns descriptions keyed
by page number, which `_extract_typed_pages()` appends to that page's prose — an earlier
version substituted Docling's `<!-- image -->` markdown placeholder, which never appears
in `doc.texts`, so every image was silently dropped.

---

### `ingestion/image.py`

**What it does:** OCR *and* vision description of a standalone image, fused into one
passage.

**Why it exists:** Neither approach alone is sufficient. PaddleOCR reads printed text
accurately but knows nothing about layout or content. A VLM describes the scene well but
misreads dense text. A diagram with labels needs both.

**Non-obvious behavior:** Fusion is itself an LLM call (qwen2.5:3b, explicit `model=`).
If only one source produced output it's returned directly — no pointless LLM call. If
fusion fails, it falls back to concatenating both under headings.

**Design decisions:** PaddleOCR is `lru_cache`'d because construction is expensive. The
field-extraction loop checks both `rec_texts` and `text_word` because PaddleOCR renamed
that field between versions.

---

### `ingestion/text.py` · `video.py` · `youtube.py`

`text.py` is the simplest ingestor — read the file. `ingest_string()` writes pasted text
to a temp file and delegates to the normal path rather than duplicating the pipeline.

`video.py` transcribes via Whisper.

`youtube.py` downloads audio with yt-dlp then transcribes. URL validation is an **exact
netloc match** against a fixed domain set, not a substring check — `evil.com/youtube.com`
is correctly rejected.

---

### `ingestion/helpers.py`

**What it does:** Cross-ingestor utilities: `transcribe()`, `describe_image()`,
`vision_with_timeout()`, `delete_source()`.

**Non-obvious behavior:** Whisper loads with `device="mps"` when available but keeps
`fp16=False` **regardless of device** — Whisper's fp16 path has known MPS bugs. Whisper's
own `load_model()` only auto-detects CUDA→CPU and never MPS, which is why this wrapper
does its own detection.

`vision_with_timeout()` uses `ThreadPoolExecutor`, never `signal.alarm()` — signals only
work on the main thread and only on POSIX, and this runs on a worker thread.

**Design decisions:** `delete_source()` is a **standalone function, not a method**,
because deletion is triggered from the API without an ingestor instance. It removes
chunks, summary, graph data *and* clears the cache — four systems that must stay
consistent, which is exactly why it's one function instead of four call sites.

---

### `retrieval/embed.py`

Thin façade over the Ollama client plus `chunk_text()`. Its value is being the **single
import point** — ingestion, retrieval and the ML scripts all embed through here, so
there's no way for two paths to drift onto different models or parameters.

---

### `retrieval/search.py`

**What it does:** Hybrid BM25+vector retrieval with RRF (`search`), and Stage 1 summary
retrieval (`search_summaries`).

**Key functions:** `_build_filter()` (handles ChromaDB's mandatory `$and` for
multi-field filters, and `$in` for multiple sources), `_rrf()`, `_rank_indices()`.

**Design decisions:** Covered in §2.6 — BM25 over the candidate pool only, and RRF over
raw score blending.

---

### `retrieval/reranker.py`

**What it does:** Cross-encoder reranking.

**Non-obvious behavior:** Module-level singleton — the model loads once on first use (or
during startup warmup) and is reused. Device selection prefers MPS, then CUDA, then CPU.
Two fallback layers: batch failure drops to a per-item loop; load failure returns the
original order with score 1.0.

**Design decisions:** float32, confirmed to produce no NaNs (the docstring records the
actual test output). `MAX_LENGTH=512` is the model's limit. Loaded from HuggingFace via
`transformers` rather than Ollama, because Ollama doesn't serve cross-encoders.

---

### `retrieval/graph.py`

**What it does:** Entity/relationship extraction, per-user SQLite storage, BFS querying.

**Non-obvious behavior:** Table names interpolate `user_id` directly, because SQLite
cannot parameterize identifiers. `_validate_user_id()` enforces `^[A-Za-z0-9_]+$` and
raises otherwise — **that check is the only thing standing between this and SQL
injection**, so never add a path that skips it.

`_strip_latex()` is knowingly lossy: it strips `{}` and `\` globally, which also mangles
code snippets and embedded JSON. Accepted because malformed LaTeX breaks JSON generation
far more often than code appears in these documents.

`has_graph()` swallows `OperationalError` and returns `False` — the tables genuinely
don't exist until the first build.

---

### `retrieval/pipeline.py`

**What it does:** DSPy signatures, `RAGPipeline`, and the prompt builders.

**Non-obvious behavior:** The pipeline is split into `search_candidates()` (stages 1-3)
and `rerank_candidates()` (stages 4-5) specifically so the streaming API can emit
`[STAGE]` events between them. `forward()` and `retrieve_context()` compose both.

`_retrieve()` takes both a `query` and an `original_question` because the ML scripts
search with a rewritten query but score against the user's original phrasing.

**Design decisions:** **Generation is deliberately not DSPy.** `dspy.Predict` doesn't
stream token-by-token, and streaming is essential to perceived speed when generation
takes 20 seconds. So `build_answer_prompt()` reproduces the `RAGAnswerer` signature as
plain text for `generate_stream()`. `RAGAnswerer` still backs the non-streaming
`forward()`. That's real duplication — the same instructions exist as a signature and as
a prompt string — and it's the price of streaming.

`QueryRewriter` is retained but never called in `forward()`: rewriting cost 25-30s for
marginal gain. It can't be deleted because `ml/eval.py` and `ml/collect_pairs.py` call
`pipeline.rewriter` directly.

---

### `api/query.py`

**What it does:** All four query endpoints.

**Non-obvious behavior:** both `POST /query` and `POST /query/stream` consult the
semantic cache, but source-filtered queries skip it in both directions (cached context
was built under a different filter). A streaming cache hit emits no
`traversing_graph`/`reranking` stage events. `_sse_token()` JSON-encodes tokens
(§2.9). Attachment uploads are written to temp files *before* the generator starts,
because `UploadFile` handles don't survive into a streaming generator, and are removed in
a `finally`.

**Design decisions:** Attachments are **never ingested** — no ChromaDB writes, no
chunking, no embedding. They're per-turn context prepended to the question. Asking one
question about a PDF shouldn't permanently add it to your knowledge base; that's what the
ingest panel is for. Follow-up turns still work because the frontend folds the stored
description back into history.

---

### `api/ingest.py` · `documents.py` · `sources.py` · `sessions.py` · `settings.py` · `title.py` · `compact.py`

`ingest.py` — upload endpoints. Saves originals for preview, slugifies YouTube titles,
strips `&t=`/`?t=` params that break yt-dlp.

`documents.py` — list/read/delete sources and run analysis. Every ChromaDB call is
wrapped in `asyncio.to_thread()` because the client is synchronous and would otherwise
block the event loop. It also guards against `metadatas` being `None` on empty
collections in some ChromaDB versions.

`sources.py` — serves stored original files for preview. Sends **`Vary: Origin`** on
every response: the same URL is fetched both as a plain `<img src>` (no `Origin` header,
so no `Access-Control-Allow-Origin` in the response) and via `fetch()` (a CORS request
that requires it). Without `Vary`, the browser reuses the cached non-CORS response for
the CORS request and it fails with a *misleading* "blocked by CORS policy" error on a
file that serves perfectly well.

`sessions.py` — a one-shot flag consumed on read, so `reset_all.sh` can tell the frontend
to wipe its localStorage.

`settings.py`, `title.py`, `compact.py` — small and self-explanatory. `compact.py` calls
`ollama.chat` directly rather than `generate_stream()` because it wants one blocking
completion, not a stream.

---

### `analysis/fact_check.py` · `contradiction.py` · `common.py`

Optional, user-triggered quality passes over an already-ingested source. Both prompt for
a `VERDICT:`/`REASON:` format parsed by the shared `parse_verdict()`, and both write
results back into chunk metadata via `update_chunk_metadata()`. Defaults are chosen so a
malformed response **never** flags content — a false "this is wrong" badge is worse than
a missed one.

---

### `utils/chromadb_client.py`

Shared embedded client plus the two per-user collection getters. **Per-user isolation
lives only here** — no other module constructs a collection name. Both collections use
`{"hnsw:space": "cosine"}`. The summaries collection is `user_{id}_summaries` — plural,
and an easy typo.

---

### `utils/ollama_client.py`

**Non-obvious behavior:** `_extract_single_embedding()` and `_extract_batch_embeddings()`
look absurdly defensive — they accept typed objects, dicts, and bare lists. That's
because ollama-python has changed its embedding response type across versions, and this
is the seam that keeps an upgrade from silently breaking all embedding.

`embed_batch()` tries one batch call, then falls back to parallel per-item calls capped
at 8 threads (local Ollama saturates quickly).

**The trap:** `generate_stream(prompt, system=None, model=None)` defaults to
`get_model("answer")` — **qwen3**. Any "fast" task that forgets `model=` silently runs on
the slow thinking model. Only `ml/generate_eval.py` legitimately relies on the default.

---

### `utils/cache.py`

**What it does:** Semantic query cache keyed on the **query embedding**, not the query
string, so paraphrases hit (cosine ≥ 0.85, 24h TTL).

**Non-obvious behavior:** It stores **retrieval context, never answers** — a hit reuses
the retrieved chunks but regenerates the answer against the new phrasing. This is the
right call: two similar questions deserve two answers, but they rarely deserve two
retrievals. Lookup is a linear scan with numpy cosine over all of the user's rows —
fine at personal scale, and the thing to replace first if the corpus grows.

**But see §7: nothing in the running app calls it.**

---

### `utils/telemetry.py`

Fire-and-forget POST to the Pi on a daemon thread with a 2-second timeout, wrapped in a
bare `except: pass`. That's one of the few places a silent catch is correct — an
unreachable Pi must never slow down or break a user request. Payloads carry `DEVICE_ID`,
never `USER_ID`, and never content.

---

### `frontend/lib/api.ts`

Every API call, typed, in one file. `consumeQueryStream()` is the single SSE parser
shared by all three streaming functions — covered in detail in §2.10.

### `frontend/hooks/`

`useChat` is the complex one (§2.1-2.2): multi-session state in localStorage, the
abort-then-send guard, the generation counter, auto-compaction, and the attachment
round-trip via `historyContent()`.

`useIngestion` uses a **recursive `setTimeout`, not `setInterval`**, so the poll interval
adapts (1s queued / 2s ingesting / 3s otherwise) and stops entirely when nothing is
active. Cancelled jobs go into `hiddenJobIds` immediately, because filtering the local
array would be undone by the very next poll.

`useSources` and `useSettings` are straightforward.

### `frontend/components/`

`app/page.tsx` owns source selection and the direct-mode decision. `MessageBubble`
renders markdown + KaTeX and the citation modal (normalizing reranker logits through
`relevancePercent`). `SourcesModal` lazy-loads thumbnails via `IntersectionObserver` and
sniffs content-type with a HEAD request before choosing a preview renderer; both its
effects use `AbortController` so a component unmounting mid-flight can't paint a stale
error.

---

### `ml/` and `scripts/`

`ml/` is offline tooling, never imported by the server: `eval.py` (top-k accuracy and MRR
to Weights & Biases), `generate_eval.py`, `collect_pairs.py` (reranker training pairs,
unused so far), `finetune_embed.py`, `common.py`.

`scripts/`: `install.sh` (first-time setup; requires Python 3.13+, matching `pyproject.toml`), `start.sh` (update check, both processes, conditional frontend rebuild),
`reset_all.sh` (wipes all state and drops the session-reset flag), `status.sh`,
`ingest_training_data.sh`, `metrics.ipynb` (gitignored — contains the private Pi IP).

---

## 6. Architecture decisions

Every one of these is a trade, so each is stated with what it cost.

### Embedded ChromaDB, not server mode
**Why:** `PersistentClient(path=...)` runs in-process. No Docker, no daemon, no port, no
connection pool, no startup ordering. Distribution becomes "clone and run," which for a
tool one person installs on their own laptop is worth a great deal.
**Cost:** Single process. The API and the ingestion worker must share one client, and
there's no path to a second machine without changing this.

### SQLite for the cache, not Redis
**Why:** Redis was the only remaining reason to require Docker. At single-user scale a
local file with a linear scan over a few hundred rows is indistinguishable in latency,
and it persists across restarts for free.
**Cost:** The lookup is O(n) over the user's cached rows. At tens of thousands it would
need an ANN index — but a personal cache won't get there.

### SQLite + NetworkX for the graph, not a graph database
**Why:** Same reasoning. The graph is small enough to load into NetworkX per query, and
Neo4j would be another service to install and run.
**Cost:** `query_related_sources()` loads **all** nodes and edges and rebuilds the
DiGraph on every call. That's fine at thousands of edges and would not be at millions.

### Two-phase ingestion
**Why:** Entity extraction is one LLM call per chunk — minutes for a large document —
and it only improves recall rather than enabling retrieval. Making it blocking would mean
staring at a spinner for something you don't need yet.
**Cost:** A window where a source is queryable but graph-augmented recall isn't
available. The UI shows an amber dot for it.

### Sequential graph queue
**Why:** Measured. Parallel builds all contend for a single local Ollama process; making
them concurrent made total throughput *worse*, not better.
**Cost:** Graph builds for many documents complete strictly one after another.

### Hybrid BM25 + vector, fused with RRF
**Why:** Embeddings smear exact tokens — error codes, identifiers, proper nouns — into
semantic neighborhoods. BM25 catches them. RRF fuses using **rank only**, so it needs no
per-corpus weight calibration the way score blending does, and `k=60` comes from the
original paper.
**Cost:** BM25 only re-scores the vector candidate pool, so it can reorder but never
rescue a chunk vector search missed entirely.

### Cross-encoder reranking on ~20 candidates
**Why:** Bi-encoder retrieval scores question and chunk independently; a cross-encoder
reads them together and is substantially more accurate. Cheap-and-broad then
expensive-and-narrow is the standard shape for good reason.
**Cost:** A second model outside Ollama (HuggingFace `transformers`), ~2GB of RAM, and a
cold-start penalty mitigated by startup warmup.

### Base reranker, no fine-tuning
**Why:** BGE-Reranker-v2-m3 performed well enough out of the box that a training loop
wasn't justified. `ml/collect_pairs.py` exists for if that changes.
**Cost:** Not adapted to this specific corpus.

### bge-m3 for embeddings
**Why:** Strong retrieval quality, multilingual, runs under Ollama so it's one less
runtime. 1024 dimensions.
**Cost:** Changing embedding model requires deleting and recreating both collections —
Chroma won't mix dimensions.

### qwen3 for answers, qwen2.5:3b for everything else
**Why:** This is the most consequential routing decision in the project. qwen3 is a
*thinking* model: better reasoning, but slow and token-hungry. That's an acceptable
trade **once per query** for the one output a human reads. It's a terrible trade for the
high-volume, low-judgement work — one summary per document, one cleanup per page, one
extraction per chunk — where qwen2.5:3b is ~5× faster and just as good. Being
non-thinking also means `dspy.Predict` works without `AdapterParseError`.
**Cost:** Two models resident. And a real footgun: `generate_stream()` defaults to
qwen3, so a forgotten `model=` silently runs the slow model.

### DSPy for structured extraction, not for generation
**Why:** For `TextCleanup` and `TranscriptionRefinement`, typed signatures with declared
fields beat a hand-rolled prompt plus regex parsing — the contract is explicit and
`TranscriptionRefinement` can carry a worked example inline. But `dspy.Predict` does not
stream token-by-token, and streaming is what makes a 20-second generation feel
acceptable. So user-facing answers use `generate_stream()`.
**Cost:** `RAGAnswerer`'s instructions exist twice — once as a signature, once as
`build_answer_prompt()`. They can drift.

### LLM fallback instead of refusal
**Why:** When nothing clears the rerank threshold, answering from the model's own
knowledge is more useful than "I don't know." The absence of citations makes it
self-evident which mode you got.
**Cost:** An ungrounded answer can look like a grounded one to someone not watching the
citation chip.

### Client-persisted chat sessions
**Why:** No backend table, no migration, no sync. The browser already does this well.
**Cost:** History doesn't follow you across browsers or machines, and clearing site data
destroys it.

### Anonymous telemetry to a Pi
**Why:** Real usage data — latency distributions, cache behavior, ingestion durations —
without collecting anything sensitive. `DEVICE_ID` is deliberately separate from
`USER_ID` so telemetry can never be joined to the user's data.
**Cost:** One more machine in the story, and a hardcoded Tailscale IP.

---

## 7. Known tradeoffs and rough edges

Honest list. These are the things a new hire would otherwise discover the hard way.

### The semantic cache is coarse by design
Now wired into both `POST /query` and `POST /query/stream`. Two caveats worth knowing:

Any question within cosine 0.85 of an earlier one reuses that question's retrieval.
That's usually right — "what is BPM?" and "explain business process management" deserve
the same chunks — but a genuinely different question that happens to land inside the
radius gets the wrong context, and the only signal is a subtly off answer. The threshold
is a blunt instrument.

Lookup is a **linear scan** with numpy cosine over all of the user's cached rows. Fine at
personal scale; the first thing to replace if the corpus and query volume grow.

Source-filtered queries skip the cache entirely in both directions, because cached
context was built under a different filter and reusing it would surface chunks from
sources the user deliberately deselected. That means power users who always filter never
benefit from it.

### Reranker scores are unbounded logits
Roughly -10 to +8, not calibrated across questions, not probabilities. Only relative
order is meaningful. Anything displaying them must normalize (the frontend uses a
sigmoid). `RERANKER_MIN_SCORE = -8.0` is therefore an empirical cutoff, not a principled
one, and would need retuning if the reranker changed.

### The SSE contract spans two files
`api/query.py::_sse_token` and `frontend/lib/api.ts::consumeQueryStream` are a matched
pair. Tokens are JSON-encoded so newlines survive the blank-line frame delimiter; change
one side alone and every markdown list in every answer silently collapses onto one line.
There is no test enforcing this — only the comments in both files.

### Chunking is word-based, not token-based
512 words ≈ 680 tokens for English, but the ratio varies by language and by how much code
or math a document contains. It needs no tokenizer, which is why it was chosen, but chunk
sizes in tokens are approximate and could exceed a model's window in pathological cases.

### `_strip_latex()` is lossy on purpose
It strips `{}` and `\` globally before entity extraction, which mangles code snippets and
embedded JSON along with LaTeX. Accepted because malformed LaTeX breaks JSON generation
far more often than code appears in these documents — but it does mean entity extraction
over a programming document is degraded.

### Cancellation can't interrupt a blocking call
A job inside a 90-second VLM call keeps running until it returns, regardless of the
cancel flag.

### The queue is a JSON file
Simple, atomic, survives restarts, human-readable. Also: full rewrite on every status
update, and one process only. Correct at this scale; the first thing to change if
ingestion ever goes multi-process.

### No tests
There is no test suite. Verification is manual, via `.ai/skills/frontend-testing.md`
(headless Playwright driving the real UI). That skill's regression list encodes the bugs
that have actually shipped — whitespace loss in streaming, markdown collapse, negative
match percentages, the CORS cache poisoning — because those are the ones that a
type-check and a lint pass will never catch.
