# RAGbase Backend Skill

Everything needed to work on any Python file here without asking a clarifying question.
Read `.ai/instructions.md` first for the project-wide picture; this file is the
backend-specific depth.

## Stack

- **FastAPI** — lifespan context manager, `Form(...)` for multipart, Pydantic for JSON bodies
- **ChromaDB** — embedded `PersistentClient` at `data/chromadb/`, no server, no Docker
- **SQLite** — knowledge graph (`data/knowledge_graph.db`) + semantic cache (`data/cache.db`), both WAL
- **DSPy 3.2.1** — signatures in `retrieval/pipeline.py` only
- **Ollama** — all LLM/embed traffic via `utils/ollama_client.py`
- **anydoc** (`firecrawl-anydoc`) — pure-Rust document → Markdown. Primary extractor
  for typed PDFs and every office format. **Always call it through
  `ingestion/anydoc_convert.py`**, which runs it in a child process: it can OOM the
  whole server on a large document (see §8 of `.ai/instructions.md`)
- **BGE-Reranker-v2-m3** — via `transformers`, float32, MPS/CUDA/CPU auto, batched

```bash
python3 -m uvicorn main:app --port 8001      # never bare `uvicorn` (system Python)
source .venv/bin/activate && ruff format . && ruff check . --fix   # after every edit
```
Never use `--reload` while ingesting — it restarts mid-job and kills the worker thread.

---

## Non-obvious patterns you must understand

### Two-phase ingestion — and why

Entity extraction runs one LLM call **per chunk**. On a 30-page PDF that's minutes.
Doing it inline would mean a document isn't searchable until the graph finishes, which
is the wrong tradeoff: the graph only *improves recall*, it isn't required to answer.

So `BaseIngestor.ingest()` splits:

**Phase 1 — synchronous, on the ingestion worker.**
`extract_text()` → `chunk_text()` → `store()` → summary → `store_summary()` →
status `"ingested"` → `clear_cache(user_id)` → telemetry `"ingest"`.
At `"ingested"` the source is **fully queryable**. Never make the UI wait for `"done"`.

**Phase 2 — deferred, on a *different* queue.**
`enqueue_graph_build()` sets `"waiting_for_graph"` and hands a callback to the graph
queue. The callback (`_build_graph_background`) sets `"building_graph"`, runs
`build_from_chunks()`, sets `"done"`, sends telemetry `"graph_complete"`.

### Why the graph queue is separate from the ingestion queue

Both are single-worker, but they are *independent* queues (`_queue` and `_graph_queue`
in `ingestion/queue.py`). If graph builds shared the ingestion queue, a slow graph build
would block the next document's Phase 1 — defeating the entire point of deferring it.
If they ran unbounded in threads, N documents finishing together would launch N
concurrent `extract_entities()` runs against a single local qwen2.5:3b process, which
made throughput *worse*. One dedicated sequential worker is the middle ground.

### Cache invalidation

`utils/cache.py` keys on the **query embedding**, not the query string — a hit means
"a semantically similar question was asked" (cosine ≥ 0.85, 24h TTL). It stores
**retrieval context only, never answers**, so a hit still regenerates a fresh answer
against the new phrasing.

Invalidated by `clear_cache(user_id)` in exactly two places:
1. End of Phase 1 of every ingest — new content must not be masked by stale retrieval.
2. `ingestion/helpers.py::delete_source()` — deleted content must not resurface.

> **Know this before you touch it:** `POST /query/stream` consults the cache *before*
> Stage 1, so a hit skips retrieval entirely and emits no `traversing_graph`/`reranking`
> stage events. Source-filtered queries bypass it in both directions — cached context was
> built under a different filter and would leak deselected sources. Cached entries carry
> `chunks` too, because the citation modal needs the chunk text.

### When to use `get_model()` vs a literal

Always `get_model("<task>")`. There is no case where a model name string belongs in
application code. Adding a new use means adding a **new task key** to
`config/models.py`, even if it maps to a model another key already uses —
`entity_extraction` and `summarize` both resolve to `MODEL_FAST`, and that's correct:
the keys are semantic, so routing can diverge later without touching call sites.

**The trap:** `generate_stream(prompt, system=None, model=None, think=None)` defaults to
`get_model("answer")` — **qwen3**. A "fast" task that forgets `model=` silently runs on
the slow thinking model. Always read the call site; never infer from context.
Currently only `ml/generate_eval.py` relies on the default.

**`think`** is Ollama's reasoning toggle. Leave it `None` to keep the model's default;
`False` suppresses qwen3's thinking pass entirely. User-facing answers don't set it at
the call site — they go through `api/query.py::_answer_stream()`, which applies
`ANSWER_THINKING_ENABLED`. Putting `/no_think` in a prompt does **not** work; it is
ignored and makes qwen3 think *more* (§8 of `.ai/instructions.md`).

### ChromaDB collection naming

- Chunks: `user_{user_id}`
- Summaries: `user_{user_id}_summaries` — **plural**, and easy to typo

Both created with `metadata={"hnsw:space": "cosine"}`. Per-user isolation lives *only*
in `utils/chromadb_client.py`; no other module builds a collection name.

Because bge-m3 emits 1024-dim vectors, **switching embedding models requires deleting
and recreating both collections** — Chroma will not mix dimensions.

Multi-field filters need an explicit `$and`:
```python
collection.get(where={"$and": [{"source": source}, {"chunk_index": idx}]})
```

In `async def` routes, wrap Chroma calls in `asyncio.to_thread()` — the client is
synchronous and will block the event loop otherwise (see `api/documents.py`).

### Why SQLite WAL mode

Both `cache.db` and `knowledge_graph.db` are written by the background graph thread and
the ingestion worker while the API reads them. In the default rollback journal a writer
blocks all readers. WAL lets readers proceed during a write, which is exactly this
access pattern. Pair it with `timeout=30` on **every** `sqlite3.connect()` so a
contended write waits instead of raising `database is locked`.

### Per-user graph tables

`nodes_{user_id}` / `edges_{user_id}` are interpolated into SQL because SQLite can't
parameterize identifiers. `_validate_user_id()` enforces `^[A-Za-z0-9_]+$` first and
raises otherwise. **Never call a graph function that skips that validation.**

---

## Retrieval, stage by stage

`RAGPipeline` in `retrieval/pipeline.py`:

| Stage | Function | What it does |
|---|---|---|
| 1 | `search_summaries()` | Which *documents* matter. `n_results = min(max(3, total//3), 8)`, drops cosine distance > `SUMMARY_DISTANCE_THRESHOLD` (0.7), unfiltered fallback if all exceed it |
| 2 | `query_related_sources()` | Graph augmentation, NetworkX BFS 2 hops. Skipped entirely unless `has_graph()` |
| 3 | `search()` | Hybrid: vector fetches `TOP_K_CANDIDATES` (20), BM25 re-scores **only that pool**, RRF (k=60) fuses, top `MAX_FINAL_RESULTS` (5) |
| 4 | `rerank()` | Cross-encoder, all pairs in one batched forward pass |
| 5 | `rerank_candidates()` | Drops below `RERANKER_MIN_SCORE` (-8.0); if nothing survives, empty context → LLM answers from own knowledge |
| 6 | caller | `build_answer_prompt()` → `generate_stream()` on qwen3 |

`search_candidates()` (1-3) and `rerank_candidates()` (4-5) are deliberately separate so
`api/query.py` can emit `[STAGE]` SSE events between them. `forward()` and
`retrieve_context()` compose both via `_retrieve()`.

**Generation is intentionally not DSPy.** `dspy.Predict` doesn't stream token-by-token,
so user-facing answers go through `generate_stream()` with `build_answer_prompt()`,
which mirrors the `RAGAnswerer` signature in plain text. `RAGAnswerer` is still used by
the non-streaming `forward()`.

**Reranker scores are raw unbounded logits (~-10..+8), not probabilities.** Never
`* 100` them for display. Never `softmax` them.

---

## DSPy notes

- `dspy.LM(model=f"ollama/{model}", api_base=url)` — no `api_key=""`.
- Prefer per-module `.set_lm()` over `with dspy.context(lm=...)`; see
  `pdf.py::_extract_typed_pages` for the pattern.
- All four signatures use `dspy.Predict`. qwen3 is a *thinking* model and can throw
  `AdapterParseError` with `Predict` — if that happens, switch that signature to
  `ChainOfThought`. qwen2.5:3b is non-thinking, so `Predict` is correct and
  `ChainOfThought` would just burn tokens.
- `configure_dspy()` sets the global LM once at startup (qwen3). Modules that need the
  fast model set their own LM explicitly.

---

## Common mistakes

**Hardcoding a model name**
```python
generate_stream(prompt, model="qwen2.5:3b")        # ✗
generate_stream(prompt, model=get_model("title"))  # ✓
```

**Forgetting `model=` on a fast task** — silently runs on qwen3, ~5× slower.
```python
summary = "".join(generate_stream(prompt))                              # ✗ qwen3
summary = "".join(generate_stream(prompt, model=get_model("summarize"))) # ✓
```

**Blocking the event loop with a sync client**
```python
results = collection.get(include=["metadatas"])                        # ✗ in async def
results = await asyncio.to_thread(lambda: collection.get(...))         # ✓
```

**Forgetting `$and` on a multi-field Chroma filter** — silently returns wrong rows.
```python
collection.get(where={"source": s, "chunk_index": i})                  # ✗
collection.get(where={"$and": [{"source": s}, {"chunk_index": i}]})    # ✓
```

**Bare except, or catching without logging**
```python
except Exception:
    pass                                                               # ✗
except sqlite3.OperationalError as e:
    logger.warning(f"Graph read failed for '{source}': {e}")           # ✓
```

**Crashing the pipeline on one component failure** — every optional stage degrades:
OCR failure → `""`, reranker load failure → original order, cache failure → `None`.
Match that.

**Non-atomic JSON writes** — a crash mid-write corrupts the queue status file.
```python
json.dump(status, open(path, "w"))                                     # ✗
# write tmp, then os.replace(tmp, path)                                # ✓
```

**`signal.alarm()` for timeouts** — not thread-safe and POSIX-only. Use
`ThreadPoolExecutor`; see `helpers.py::vision_with_timeout`.

**Importing a heavy dependency at module top** — `docling`, `pdf2image`, `yt_dlp`,
`fitz` and `paddleocr` are imported inside the function that needs them so server
startup stays fast. Keep the explanatory comment when you add one.

**Assuming `"done"` means queryable** — `"ingested"` is the queryable state. `"done"`
only adds the knowledge graph.

**Changing SSE token framing on one side only** — `api/query.py::_sse_token` and
`frontend/lib/api.ts::consumeQueryStream` are a matched pair. Tokens are JSON-encoded
so newlines survive the blank-line frame delimiter; break that and every markdown list
in every answer collapses onto one line.

---

## Where things live

| Need to... | Go to |
|---|---|
| Add a tunable constant | `config/settings.py` |
| Route a new LLM task | `config/models.py` (`get_model`) |
| Add a file path | `config/paths.py` |
| Add a new source format | new `BaseIngestor` subclass + a branch in `queue.py::_worker` + an extension set in `config/settings.py` (and `ACCEPTED_INGEST_TYPES` in `frontend/lib/config.ts`) |
| Convert an office/e-book format | it already works — `ingestion/office.py` covers 20 extensions via anydoc |
| Change retrieval behavior | `retrieval/pipeline.py` / `retrieval/search.py` |
| Add an endpoint | new or existing router in `api/`, then register in `main.py` **and** update §7 of `.ai/instructions.md` |
| Touch entity extraction | `retrieval/graph.py` |
