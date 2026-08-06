# RAGbase Backend Skill

## Stack

- **FastAPI** — lifespan context manager, `Form(...)` for multipart, Pydantic for JSON bodies
- **ChromaDB** — embedded `PersistentClient` at `data/chromadb/`, no Docker
- **SQLite** — knowledge graph (`data/knowledge_graph.db`) + semantic cache (`data/cache.db`, WAL mode)
- **DSPy 3.2.1** — signatures in `retrieval/pipeline.py` only
- **Ollama** — all LLM/embed calls via `utils/ollama_client.py`
- **BGE-Reranker-v2-m3** — float32, MPS/CUDA/CPU auto, batched, warmed on startup

Run: `python3 -m uvicorn main:app --host 0.0.0.0 --port 8001`
Never use bare `uvicorn` (resolves to system Python).
Never use `--reload` during ingestion runs (kills mid-ingest).

---

## Key Conventions

1. Never duplicate code.
2. All constants in `config/settings.py`. Never hardcode values elsewhere.
3. All model routing through `get_model(task)` in `config/models.py`. Never hardcode model names.
4. All Ollama calls through `utils/ollama_client.py` — except DSPy internal reasoning calls.
5. Per-user isolation only in `utils/chromadb_client.py`.
6. Graceful degradation — never crash the whole pipeline for one component failure.
7. Atomic writes: temp file + `os.replace()` for all persisted JSON.
8. Logging via `setup_logging(__name__)` — never bare `print()`.
9. Run scripts with `python3 -m` from project root.
10. Type hints + docstrings on all public functions.
11. Style: line length 100, double quotes, f-strings, early returns over nested if/else.
12. Imports: stdlib → third-party → local. No local imports inside function bodies unless avoiding circular imports (add comment).
13. No bare exceptions — catch specific types, always log with context.
14. No `.env` file — all config in `config/settings.py`; runtime overrides in `data/settings.json`.
15. No `user_id` in any API request — backend reads `USER_ID` from `config/runtime.py`.

---

## Model Routing

Always use `get_model(task)` from `config/models.py`:

| Task key | Model |
|----------|-------|
| `answer`, `query_rewrite` | `qwen3` |
| `fact_check`, `contradiction`, `summarize`, `text_cleanup`, `title` | `qwen2.5:3b` |
| `vision_handwrite`, `vision_diagram`, `vision_simple` | `qwen2.5vl` |
| `embed` | `bge-m3` |

Never reference model name strings outside `config/models.py`. `retrieval/graph.py::extract_entities()`
routes through `get_model("entity_extraction")` — a dedicated task key (maps to the same
`MODEL_FAST` model as `"summarize"`, but semantically distinct). `query_rewrite` and
`vision_diagram` are defined task keys not currently invoked anywhere — harmless, but don't
assume every key is reachable.

**Trap:** `utils/ollama_client.py::generate_stream(prompt, system=None, model=None)` defaults
`model` to `get_model("answer")` (qwen3) when the caller omits it. Only `ml/generate_eval.py`
currently relies on this default. `analysis/fact_check.py`, `analysis/contradiction.py`, the
document-summary generation in `ingestion/base.py`, and the OCR/VLM fusion in `ingestion/image.py`
all pass an explicit `model=get_model(...)` and run on `qwen2.5:3b`. Still, don't assume a "fast
task" is on the fast model without checking whether `model=` is actually passed — this has
drifted before.

---

## Ingestion Pipeline

Two-phase design in `ingestion/base.py`:

**Phase 1** (fast, synchronous): `extract → chunk → store → summary`
- Marks job `"ingested"` — source is immediately queryable.
- Re-ingesting a source that already has chunks wipes its prior chunks/graph data first.
- Calls `clear_cache(user_id)` after store.
- Sends telemetry event `"ingest"`.

**Phase 2** (background): graph build via dedicated queue
- `enqueue_graph_build()` puts the job on a **separate single-worker queue** in `ingestion/queue.py`.
- Job transitions: `waiting_for_graph → building_graph → done`.
- Graph builds across sources are **always sequential** — never parallel. This prevents multiple `extract_entities()` calls contending for `qwen2.5:3b`.
- Sends telemetry event `"graph_complete"`.

`BaseIngestor` subclasses (`PdfIngestor`, `ImageIngestor`, `VideoIngestor`, `YoutubeIngestor`,
`TextIngestor`) implement only `extract_text()`. Everything else (chunking, storing, graph
enqueueing) is in `base.py`.

`delete_source()` is standalone in `ingestion/helpers.py` — not on the ingestor class. It
removes chunks, the summary, graph data, and clears the cache.

**OCR note:** `PdfIngestor.extract_text()` creates `DocumentConverter()` with no OCR
configuration at all — no `ocr_options=` is set. This means typed-PDF OCR actually runs on
whatever Docling's default OCR engine is (EasyOCR per current Docling docs), not RapidOCR.
`rapidocr` isn't even a declared dependency in `pyproject.toml`. If RapidOCR was the intended
engine, `ocr_options=` needs to be set explicitly on the `PdfFormatOption`. Flagged for human
review — not changed, since it's a real behavioral choice (dependency + quality/speed tradeoff),
not a mechanical fix.

Job statuses: `queued → ingesting → ingested → waiting_for_graph → building_graph → done`
Error status: `"error: <detail>"` string, checked via `.startswith("error")`.
Startup reconciliation: any job left in an active status is reset to `"queued"` and
re-enqueued, provided its status file entry still has `source`, `user_id`, and `tmp_path`;
otherwise it's dropped with a warning (unrecoverable across restarts).

---

## Retrieval Pipeline

Six stages, implemented in `retrieval/pipeline.py::RAGPipeline`:

1. **Stage 1 search** — `search_summaries()`: dynamic `n_results = min(max(3, total_sources//3), 8)`, cosine distance filter > 0.7 (falls back to unfiltered if all exceed threshold)
2. **Graph augmentation** — `query_related_sources()` via NetworkX BFS (default 2 hops); skipped if `has_graph()` is False
3. **Stage 2 search** — hybrid BM25 + vector RRF (k=60), `TOP_K_CANDIDATES=20`. BM25 rescoring runs only over the vector-search candidate pool, not the full corpus.
4. **Reranking** — `BAAI/bge-reranker-v2-m3`, batched forward pass, drops chunks below `RERANKER_MIN_SCORE=-8.0`
5. **Cache check** — cosine similarity threshold `0.85`, 24hr TTL; cache stores retrieval context only, hits regenerate the answer fresh
6. **Generation** — `RAGAnswerer` DSPy signature via `qwen3`; if no chunks survive → LLM answers from own knowledge (no refusal)

`search_candidates()` (stages 1-3) and `rerank_candidates()` (stage 4) are exposed separately
so the streaming API (`api/query.py`) can emit `[STAGE]` events between them; `forward()` and
`retrieve_context()` compose both through the private `_retrieve()`.

DSPy signatures live **only** in `retrieval/pipeline.py`: `QueryRewriter`, `RAGAnswerer`,
`TextCleanup`, `TranscriptionRefinement` — all `dspy.Predict`. `QueryRewriter` is kept but not
called in `forward()` (`ml/eval.py` and `ml/collect_pairs.py` still call `pipeline.rewriter`
directly to reproduce the retrieval path for training/eval data).

---

## ChromaDB

- `PersistentClient(path="data/chromadb/")` — embedded, no server, no Docker.
- Collections: `user_{user_id}` (chunks) and `user_{user_id}_summaries` (summaries — note plural).
- Multi-field filters need explicit `{"$and": [...]}`.
- All ChromaDB calls in async FastAPI routes go through `asyncio.to_thread()`.
- When switching embedding models: delete and recreate collections (BGE-M3 = 1024-dim).

---

## SQLite

- `timeout=30` on **all** `sqlite3.connect()` calls — graph thread and queue worker contend.
- Knowledge graph: `data/knowledge_graph.db`, per-user tables `nodes_{user_id}`, `edges_{user_id}`.
  `user_id` is validated against `^[A-Za-z0-9_]+$` before being interpolated into table names.
- Cache: `data/cache.db`, WAL mode.

---

## DSPy Notes

- `dspy.LM(model=f"ollama/{model}", api_base=url)` — no `api_key=""`.
- Per-module `.set_lm()` preferred over `with dspy.context(lm=...)`.
- `qwen3` (thinking model) can cause `AdapterParseError` with `dspy.Predict` — switch that
  signature to `dspy.ChainOfThought` if that happens. All current signatures use `dspy.Predict`.
- `qwen2.5:3b` is non-thinking — use `dspy.Predict`.

---

## Timeouts

- Use `concurrent.futures.ThreadPoolExecutor`. Never `signal.alarm()`.
- Vision calls: `vision_with_timeout()` in `ingestion/helpers.py`.
- SQLite: `timeout=30`.

---

## After Any Edit

```bash
source .venv/bin/activate && ruff format . && ruff check . --fix
```

Fix all lint errors before considering the change done.
