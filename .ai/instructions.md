# RAGbase — Copilot Instructions

## What This Is

Personal AI knowledge base: ingest notes/PDFs/images/videos/YouTube, chat with all of it, grounded answers with citations. Runs entirely on personal hardware — no cloud APIs by default. Built as a portfolio project targeting ML/systems engineering roles.

**Architecture:**
- **Mac (M3)** — ALL compute: Ollama inference, ingestion pipelines, FastAPI backend, ChromaDB (embedded in-process), SQLite knowledge graph + cache
- **Raspberry Pi 5** (Tailscale `100.80.105.44`, user `tlayers21`) — telemetry only: small FastAPI server + SQLite at `~/telemetry/`, port 9000
- **Next.js frontend** — runs locally at `localhost:3000`, talks to FastAPI at `localhost:8001`
- Pi runs zero AI compute and zero RAG logic

**GitHub:** github.com/tlayers21/ragbase

---

## Directory Structure
```
ragbase/
├── main.py FastAPI entry, lifespan, configures DSPy, starts ingestion +
│ graph-build queue workers, warms up reranker + models (answer,
│ summarize, embed, vision_simple) asynchronously on startup.
│ CORS: explicit localhost:3000 + regex allowing any localhost:<port>
│ (dev server may fall back to another port).
│ GET /health and GET / for liveness checks.
├── config/
│ ├── settings.py OLLAMA_URL + API_URL hardcoded (no .env),
│ │ CHUNK_SIZE=512, CHUNK_OVERLAP=50, TOP_K_CANDIDATES=20,
│ │ MAX_FINAL_RESULTS=5, RRF_K=60,
│ │ VISION_TIMEOUT_SECONDS=180, RERANKER_MIN_SCORE=-8.0,
│ │ OLLAMA_VISION_NUM_CTX=8192, EMBED_BATCH_SIZE=64,
│ │ HANDWRITTEN_IMAGE_THRESHOLD=5, HANDWRITTEN_TEXT_THRESHOLD=200,
│ │ CACHE_SIMILARITY_THRESHOLD=0.85, CACHE_TTL=86400,
│ │ TELEMETRY_ENABLED=True, ATTACHMENT_TEXT_MAX_CHARS=8000,
│ │ WANDB_PROJECT="ragbase", SUPPORTED_*_EXTENSIONS
│ ├── models.py get_model(task) — SINGLE source of truth for all model routing:
│ │ answer/query_rewrite → qwen3
│ │ fact_check/contradiction/summarize/text_cleanup/entity_extraction → qwen2.5:3b
│ │ title → qwen2.5:3b
│ │ vision_handwrite/vision_diagram/vision_simple → qwen2.5vl
│ │ embed → bge-m3
│ │ Raises ValueError for unknown task keys. `query_rewrite` and
│ │ `vision_diagram` are defined but not currently invoked via get_model()
│ │ anywhere in the codebase (harmless — kept for future/explicit use).
│ ├── paths.py ALL file paths, incl. KNOWLEDGE_GRAPH_DB_PATH =
│ │ data/knowledge_graph.db (not "graph.db")
│ ├── runtime.py USER_ID + DEVICE_ID (generated on first launch, persisted
│ │ to data/user_id.txt / data/device_id.txt), data/settings.json
│ │ overrides: is_telemetry_enabled(), get/set_display_name().
│ │ Atomic writes (temp file + os.replace).
│ └── logging.py setup_logging(name)
├── ingestion/
│ ├── base.py BaseIngestor(ABC). Two-phase ingestion:
│ │ Phase 1 (fast, synchronous): extract→chunk→store→summary,
│ │ marks job "ingested", source immediately queryable.
│ │ Document summary generation calls generate_stream() with an explicit
│ │ model=get_model("summarize"), so it runs on qwen2.5:3b, not qwen3.
│ │ Calls clear_cache(user_id) after Phase 1.
│ │ Re-ingesting a known source wipes its prior chunks/graph data first.
│ │ Phase 2: enqueue_graph_build() puts _build_graph_background onto
│ │ ingestion/queue.py's dedicated graph queue (marks "waiting_for_graph"
│ │ immediately) — the graph worker thread runs one build at a time
│ │ across all sources, marks "building_graph" then "done".
│ │ estimated_seconds set per source type for progress animation.
│ │ send_telemetry() called after Phase 1 ("ingest") and Phase 2
│ │ ("graph_complete"). Cancellation check at top of chunk-batch loop.
│ ├── helpers.py transcribe() (Whisper "base", MPS device when available,
│ │ fp16=False always), describe_image() (always passes filename as
│ │ context hint, task="vision_handwrite"), vision_with_timeout()
│ │ (ThreadPoolExecutor — NOT signal.alarm), delete_source()
│ │ (standalone — calls clear_cache(user_id) and removes graph data too).
│ ├── pdf.py PdfIngestor: _is_handwritten() detection,
│ │ _extract_handwritten() (Qwen2.5-VL page-by-page, progress
│ │ file resume, 3 retries escalating timeout,
│ │ TranscriptionRefinement DSPy pass to strip narration, qwen2.5:3b),
│ │ _extract_typed() → _extract_typed_pages() (groups doc.texts
│ │ by prov[0].page_no, per-page TextCleanup DSPy pass, qwen2.5:3b) +
│ │ _describe_images() (inline qwen2.5vl descriptions replacing
│ │ <!-- image --> placeholders in document order).
│ │ Cancellation check at top of page loops.
│ ├── image.py PaddleOCR for printed text + Qwen2.5-VL for visual description,
│ │ fused via generate_stream() with an explicit model=get_model("summarize")
│ │ (runs on qwen2.5:3b, not qwen3).
│ ├── video.py Whisper on local files via helpers.transcribe().
│ ├── youtube.py yt-dlp + Whisper. Strips &t=/?t= timestamp query params
│ │ before processing. URL validation is an EXACT domain match against
│ │ {youtube.com, youtu.be, www.youtube.com, m.youtube.com,
│ │ music.youtube.com} — not a substring check.
│ ├── text.py TextIngestor: reads .txt/.md files directly, plus
│ │ ingest_string() for raw pasted text (writes a temp file then
│ │ delegates to the normal ingest() path).
│ └── queue.py TWO single-worker queues: the ingestion queue and a
│ dedicated graph-build queue (enqueue_graph_build(),
│ start_graph_queue()) so graph builds across sources never run
│ concurrently and contend for qwen2.5:3b.
│ Job statuses: queued → ingesting → ingested → waiting_for_graph →
│ building_graph → done
│ estimated_seconds field per job for frontend progress animation.
│ Startup reconciliation: stale "ingesting"/other active jobs reset to
│ "queued" and re-enqueued from the status file.
│ Duplicate detection: won't enqueue same source+user if a job for it
│ is already active.
│ cancel_job() + is_cancelled() for cancellation support.
│ Error status string is "error: <detail>"; clear_completed() sweeps
│ done/cancelled/error jobs from the status file only (never touches
│ ChromaDB or the graph).
├── retrieval/
│ ├── embed.py embed() + embed_batch() + chunk_text() — single import point.
│ │ chunk_text() splits by word count (not tokens): CHUNK_SIZE=512 words,
│ │ CHUNK_OVERLAP=50 words.
│ ├── search.py hybrid BM25+vector RRF (k=60). BM25 rescoring runs only
│ │ over the vector-search candidate pool, not the full corpus.
│ │ search_summaries() for Stage 1: dynamic n_results =
│ │ min(max(3, total_sources//3), 8), filters out sources with cosine
│ │ distance > 0.7, falls back to unfiltered if all exceed threshold.
│ ├── reranker.py BAAI/bge-reranker-v2-m3, loaded fresh from HuggingFace
│ │ (no local fine-tuned checkpoint), float32, MPS/CUDA/CPU auto.
│ │ BATCHED forward pass — all pairs in one call.
│ │ Falls back to per-item loop if batch raises; falls back to original
│ │ order (score 1.0) if the model fails to load at all.
│ │ Warmed up on startup in main.py lifespan.
│ ├── graph.py extract_entities() routes through get_model("entity_extraction")
│ │ (qwen2.5:3b, a dedicated task key mapped to MODEL_FAST).
│ │ strip_latex(), validate_extracted(), string caps [:200].
│ │ json-repair used before json.loads() for robustness.
│ │ Entity filters: <3 chars, numeric-only, stop words, LaTeX fragments,
│ │ case-insensitive dedup.
│ │ has_graph(user_id) — checks if graph exists before augmentation.
│ │ build_from_chunks(), query_related_sources() (NetworkX BFS, default
│ │ 2 hops).
│ │ SQLite per-user: nodes_{user_id}, edges_{user_id} in
│ │ data/knowledge_graph.db. timeout=30 on all sqlite3.connect() calls.
│ │ user_id validated against ^[A-Za-z0-9_]+$ before being interpolated
│ │ into table names.
│ └── pipeline.py DSPy signatures: QueryRewriter (retained, unused in
│ forward()), RAGAnswerer, TextCleanup, TranscriptionRefinement — all
│ dspy.Predict (no ChainOfThought currently in use).
│ RAGPipeline.search_candidates() (stages 1-3) and rerank_candidates()
│ (stage 4) are split so the streaming API can emit [STAGE] events
│ between them. forward()/retrieve_context() compose both via _retrieve().
│ Chunk filter: drops below RERANKER_MIN_SCORE=-8.0.
│ No chunks → LLM answers from own knowledge (no retry, no refusal).
│ format_history() keeps the last 6 messages (3 turns), 300 chars each.
│ configure_dspy() sets the global DSPy LM once at startup (qwen3).
├── analysis/ fact_check.py, contradiction.py — call generate_stream() with
│ explicit model=get_model("fact_check")/get_model("contradiction"), so
│ verdicts run on qwen2.5:3b, not qwen3. common.py has shared parse_verdict() (parses
│ "VERDICT: ...\nREASON: ..." responses) and update_chunk_metadata().
├── api/
│ ├── ingest.py /ingest/file /url /text /status /clear_completed
│ │ /ingest/cancel/{job_id} /ingest/generate_title (document title,
│ │ form-encoded, qwen2.5:3b via get_model("title"))
│ │ URL ingest auto-fetches YouTube title via yt-dlp, strips &t=/?t=.
│ ├── query.py POST /query (full RAG, complete JSON response)
│ │ POST /query/stream (RAG with SSE + [STAGE] events)
│ │ POST /query/direct (no RAG, pure qwen3 SSE stream — used when the
│ │ user has deselected all sources)
│ │ POST /query/with_attachments (multipart: question, history JSON,
│ │ source_filter JSON, is_direct, attachments[]; images go through
│ │ describe_image(), PDFs through PyMuPDF one-shot extraction, text
│ │ files read directly — never ingested/indexed. Emits [ATTACHMENTS]
│ │ SSE event before generation. Supports both RAG and direct mode.)
│ │ _SYSTEM_PROMPT module constant shared by all three streaming routes.
│ │ Cache hit path: retrieve cached chunks, regenerate answer fresh.
│ │ Client-disconnect checks (await request.is_disconnected()) before
│ │ each expensive blocking step so Stop actually halts backend work.
│ │ Telemetry: query_rag vs query_direct vs query_attachments with
│ │ latency + cache_hit.
│ ├── documents.py GET /documents/ (list), GET /documents/{source}
│ │ (chunks), DELETE /documents/{source}, POST
│ │ /documents/{source}/check_facts, POST
│ │ /documents/{source}/check_contradictions. All ChromaDB calls
│ │ wrapped in asyncio.to_thread().
│ ├── sources.py GET/HEAD /sources/{source}/file — serves stored source
│ │ files. Original files stored at data/sources/{user_id}/{source}{ext}.
│ ├── sessions.py GET /sessions/should_reset — one-shot flag consumed
│ │ from data/reset_sessions_flag (created by scripts/reset_all.sh) so
│ │ the frontend knows to wipe its localStorage chat sessions.
│ ├── title.py POST /title — generates a short chat-session title from
│ │ the first user message (qwen2.5:3b via get_model("title")).
│ │ Distinct from /ingest/generate_title, which titles ingested
│ │ documents instead of chat sessions.
│ ├── compact.py POST /compact — summarizes old messages via
│ │ get_model("summarize") (qwen2.5:3b, via ollama.chat directly, not
│ │ generate_stream) for context window management.
│ └── settings.py GET /settings/user, POST /settings/telemetry,
│ POST /settings/display_name
├── ml/
│ ├── eval.py Eval pipeline — reproduces retrieval via
│ │ pipeline.rewriter + pipeline._retrieve(), logs top-k accuracy/MRR
│ │ to Weights & Biases.
│ ├── generate_eval.py Generates eval questions per chunk (LLM call has
│ │ no model arg — runs on qwen3).
│ ├── collect_pairs.py Reranker training pairs (future use)
│ ├── common.py to_chunk_index() shared by eval + collect_pairs
│ └── finetune_embed.py Embedding fine-tuning (future use)
├── utils/
│ ├── chromadb_client.py PersistentClient (embedded, no server needed).
│ │ Collections: user_{user_id}, user_{user_id}_summaries.
│ │ Data stored at data/chromadb/.
│ ├── ollama_client.py embed(), embed_batch() (batch call with parallel
│ │ per-item fallback, response-shape-tolerant across ollama-python
│ │ versions), vision(), generate_stream(prompt, system=None,
│ │ model=None) — defaults to get_model("answer") when model is omitted.
│ ├── cache.py SQLite-backed semantic cache at data/cache.db (WAL mode).
│ │ get_cached_response(), set_cached_response(), clear_cache().
│ │ Cosine similarity via numpy, threshold 0.85, 24hr TTL.
│ │ Stores retrieval context only (not answers) — cache hits regenerate
│ │ the answer fresh against the new question.
│ └── telemetry.py Fire-and-forget POST to Pi:9000/telemetry, daemon thread.
│ Checks is_telemetry_enabled() before sending.
│ Uses device_id instead of user_id in all payloads.
│ Event types: query_rag, query_direct, query_attachments, ingest, graph_complete.
├── frontend/ Next.js 16 (App Router, TypeScript, Tailwind v4)
│ ├── types/index.ts Shared types (@/types): SourceSummary, IngestionJob,
│ │ Message, ChatSession, CitedChunk, MessageAttachment,
│ │ PendingAttachment, QueryMode, AttachmentType.
│ ├── lib/config.ts DEFAULT_API_URL only — no DEFAULT_USER_ID
│ ├── lib/api.ts All typed API calls. No user_id in any request.
│ │ consumeQueryStream() is the single SSE parser shared by
│ │ streamQuery(), streamDirectQuery(), streamAttachmentQuery().
│ ├── lib/attachments.ts classifyFile(), getPdfPageCount() (lazy pdfjs-dist
│ │ import), twoLinePreview(), PASTE_TEXT_THRESHOLD=5000.
│ ├── lib/utils.ts cn() (clsx + tailwind-merge), deriveSourceName().
│ ├── hooks/ useChat (multi-session chat state, localStorage-persisted,
│ │ auto-compact, attachment round-trip), useSources, useIngestion
│ │ (polling with dynamic interval, fade-out of done jobs), useSettings.
│ ├── components/layout/ Sidebar (chat session list — new/rename/pin/
│ │ delete, collapsible, context window bar + display-name greeting in
│ │ footer), SourcesPanel (collapsible, File/Text/YouTube ingest tabs +
│ │ active job queue), ThemeToggle
│ ├── components/chat/ ChatArea (Sources button top right), MessageBubble
│ │ (ReactMarkdown + KaTeX, copy button, hover timestamp, attachment
│ │ chips, "Sources used" button → chunks modal, auto-compact summary
│ │ blocks), ChatInput (stop button during streaming, paperclip
│ │ attachment button, clipboard paste for images/long text, attachment
│ │ cards above textarea), SourceFilter (always visible, amber dot for
│ │ graph-pending sources), ModelSelector (qwen3 + "coming soon" other
│ │ models)
│ ├── components/sources/ DropZone (drag-drop fixed), SourcesModal (card
│ │ grid with lazy-loaded thumbnails via IntersectionObserver, click
│ │ into full preview pane; PDF preview via react-pdf + CDN worker,
│ │ image preview, text preview), PDFPreview, PDFThumbnail
│ ├── components/ui/ ConfirmDialog (shared confirm/cancel modal —
│ │ session delete, etc.)
│ ├── components/providers.tsx next-themes ThemeProvider wrapper
│ ├── app/page.tsx Main 3-panel layout (Sidebar | ChatArea |
│ │ SourcesPanel), owns source-selection state and the sources modal
│ └── app/settings/ Display name, API URL, theme, telemetry toggle
├── scripts/
│ ├── install.sh First-time setup: OS check (macOS/Linux), prereq checks
│ │ (Ollama, Python 3.11+, Node 18+ — note: pyproject.toml requires
│ │ Python >=3.13, stricter than this check), model pulls, uv venv
│ │ setup, npm install + production build, data dirs.
│ ├── start.sh Checks for upstream updates via the GitHub API and
│ │ `git pull`s if behind, starts backend + frontend, rebuilds the
│ │ frontend only if its source hash changed since last run, opens the
│ │ browser automatically.
│ ├── reset_all.sh Kills all RAGbase processes, clears data/chromadb/,
│ │ deletes the knowledge graph SQLite file (+ -wal/-shm), clears
│ │ cache.db, resets queue_status.json, deletes eval_set.json /
│ │ training_pairs.json / models/reranker_model.pt / logs, clears
│ │ data/sources/, and creates data/reset_sessions_flag so the frontend
│ │ clears its chat sessions on next load (consumed via
│ │ GET /sessions/should_reset).
│ ├── ingest_training_data.sh Batch-ingests every PDF in
│ │ data/training_data/ via POST /ingest/file.
│ ├── status.sh Queue status (via /ingest/status) + tail of
│ │ logs/ingestion.pdf.log.
│ └── metrics.ipynb Notebook for inspecting telemetry from the Pi
│ (not a shell script).
├── data/
│ ├── chromadb/ ChromaDB embedded storage (gitignored)
│ ├── sources/ Original uploaded files (gitignored)
│ ├── user_id.txt Auto-generated local user ID (gitignored)
│ ├── device_id.txt Anonymous telemetry device ID (gitignored)
│ ├── settings.json Local settings overrides (telemetry, display name)
│ ├── cache.db SQLite semantic cache (gitignored)
│ ├── knowledge_graph.db SQLite knowledge graph (gitignored)
│ └── queue_status.json Ingestion job status file (gitignored)
└── pyproject.toml + uv.lock uv-managed venv at .venv/ (requires-python >=3.13)
```

No `.env` file — all config defaults are hardcoded in `config/settings.py`.
---

## Coding Conventions

1. Never duplicate code.
2. All constants in `config/`. Model selection always through `get_model(task)`.
3. All Ollama calls through `utils/ollama_client.py` (except DSPy reasoning).
4. Per-user isolation only in `chromadb_client.py`.
5. Graceful degradation everywhere — never crash the whole pipeline for one component failure.
6. Atomic writes for all persisted JSON (temp file + `os.replace`).
7. Logging via `setup_logging(__name__)` — never bare `print()`.
8. Run module scripts with `python3 -m` from project root.
9. Type hints + docstrings on all public functions.
10. FastAPI: lifespan context manager, `Form(...)` for multipart, Pydantic models for JSON bodies.
11. Style: line length 100, double quotes, f-strings, early returns over nested if/else.
12. Imports grouped: stdlib, third-party, local. No local imports inside function bodies unless needed for circular import avoidance (add comment).
13. `ruff format .` after generation, `ruff check . --fix` before committing.
14. No bare exceptions — catch specific types, always log with context.
15. DSPy signatures in `retrieval/pipeline.py` only.
16. `BaseIngestor` subclasses implement `extract_text()` only.
17. `delete_source()` is standalone in `ingestion/helpers.py`.
18. Timeouts: use `concurrent.futures.ThreadPoolExecutor`, never `signal.alarm()`.
19. Verify third-party library APIs before trusting generated code — test in isolation.
20. Always `python3 -m uvicorn` — bare `uvicorn` resolves to system Python.
21. No Docker required for default setup — ChromaDB runs embedded, cache uses SQLite.
22. Frontend API calls go through `lib/api.ts` only.
23. Frontend: no hardcoded `localhost:8001` — always read from config or localStorage.
24. No user_id in any frontend API call — backend reads from data/user_id.txt.
25. No .env — all config in config/settings.py directly; runtime overrides in data/settings.json.

---

## Model Stack

| Task key (`get_model(task)`) | Model | Notes |
|------|-------|-------|
| `answer`, `query_rewrite` | qwen3 | Concise system prompt always passed in `/query*`, never narrates context. Also the **default** for any `generate_stream()` call that omits `model=` — currently only `ml/generate_eval.py` relies on that default. |
| `fact_check`, `contradiction`, `summarize`, `text_cleanup`, `title`, `entity_extraction` | qwen2.5:3b | Fast, non-thinking. Document-summary generation, fact-check, contradiction-check, image OCR/VLM fusion, and entity extraction all pass an explicit `model=get_model(...)` and run on this model, not qwen3. |
| `vision_handwrite`, `vision_diagram`, `vision_simple` | qwen2.5vl | Replaces LLaVA |
| `embed` | bge-m3 | 1024-dim |
| reranker | BAAI/bge-reranker-v2-m3 | float32, MPS, batched, warmed up on startup — loaded fresh from HuggingFace each run, no local fine-tuned checkpoint |
| OCR (standalone images) | PaddleOCR | |
| OCR (typed PDFs) | Docling's default OCR engine (EasyOCR) | **Doc/code mismatch found in 2026-08-06 audit:** `ingestion/pdf.py::extract_text()` constructs `DocumentConverter()` with no `ocr_options=` at all, so typed-PDF OCR runs on whatever Docling defaults to (EasyOCR per current Context7 docs), not RapidOCR. `rapidocr` isn't a declared dependency in `pyproject.toml` either. Docling *does* support pluggable OCR via `PdfFormatOption(pipeline_options=PdfPipelineOptions(ocr_options=RapidOcrOptions()))` — if RapidOCR was the intended engine, this needs to be wired up explicitly. Needs a human decision: keep EasyOCR (update the design intent) or add the RapidOCR dependency and wire up `ocr_options=`. |
| Handwritten PDF | qwen2.5vl | VLM only, no OCR |

Entity extraction (`retrieval/graph.py::extract_entities`) routes through `get_model("entity_extraction")` — a dedicated task key in `config/models.py` that maps to `MODEL_FAST` (same underlying model as `"summarize"`, but a distinct, semantically-correct key).

**Removed:** llama3.1:8b, llama3.2:3b, llava, nomic-embed-text, moondream, pix2text, pytesseract, Redis

---

## Known Gotchas

- **DSPy 3.2.1:** `dspy.LM(model=f"ollama/{model}", api_base=url)`. No `api_key=""`. Per-module `.set_lm()` preferred over `with dspy.context(lm=...)`. Every current signature (`RAGAnswerer`, `TextCleanup`, `TranscriptionRefinement`, `QueryRewriter`) uses `dspy.Predict`.
- **Qwen3 thinking model** — can cause `AdapterParseError` with `dspy.Predict`; if that happens, switch that signature to `dspy.ChainOfThought`. `qwen2.5:3b` is non-thinking, use `dspy.Predict`.
- **Qwen3 verbose by default** — always pass a concise system prompt to `generate_stream()` for user-facing answers. Never narrate retrieved context.
- **`generate_stream()` defaults to qwen3** — any call site that omits `model=` runs on the `answer` model, not the fast model. Document-summary generation (`ingestion/base.py`), image OCR/VLM fusion (`ingestion/image.py`), fact-check (`analysis/fact_check.py`), and contradiction-check (`analysis/contradiction.py`) all pass an explicit `model=get_model(...)` and run on `qwen2.5:3b`, not qwen3. The one current call site that genuinely omits `model=` (and so runs on qwen3) is `ml/generate_eval.py`. Always check for an explicit `model=get_model(...)` argument rather than assuming from context.
- **Docling `doc.pages` has NO text** — iterate `doc.texts` with `.prov[0].page_no`. `doc.export_to_markdown(page_no=N)` unreliable.
- **BGE-Reranker-v2-m3:** float32, no NaN, no bfloat16 needed. Scores are unbounded raw logits. Range approximately -10 to +8. `RERANKER_MIN_SCORE=-8.0`.
- **BGE-M3 produces 1024-dim** — always delete and recreate ChromaDB collections when switching embedding models. Summary collection is `user_{user_id}_summaries` (plural).
- **ChromaDB embedded** — uses `PersistentClient(path="data/chromadb/")`. No server, no Docker. Data persists across restarts automatically.
- **SQLite concurrent writes** — `timeout=30` on all `sqlite3.connect()` calls (background graph thread + queue worker contend).
- **Queue zombies** — startup reconciliation resets any job left in an active status back to `"queued"` and re-enqueues it, provided it still has `source`, `user_id`, and `tmp_path` on disk; jobs missing those fields are dropped with a warning.
- **Graph builds are sequential** — a dedicated single-worker queue in `ingestion/queue.py`
  (`enqueue_graph_build()`, started via `start_graph_queue()` in `main.py` lifespan)
  runs one source's graph build at a time, however many sources finished Phase 1
  concurrently. Prevents multiple `extract_entities()` calls hammering qwen2.5:3b.
- **Whisper on MPS** — `ingestion/helpers.py::transcribe()` loads Whisper (`"base"`) with
  `device="mps"` when available (falls back to CPU). `fp16=False` kept on
  `.transcribe()` regardless of device — Whisper's fp16 path has known MPS issues.
- **Two-phase ingestion** — source is queryable after Phase 1 ("ingested" status). Don't wait for "done".
- **ChromaDB multi-field filters** — need explicit `{"$and": [...]}`.
- **Qwen2.5-VL context** — set `options={"num_ctx": 8192}` in vision calls.
- **uvicorn --reload** — kills server mid-ingestion on package install. Never use for ingestion runs.
- **uv run / uv sync can break environment** — huggingface-hub may upgrade past 1.0, breaking transformers. Fix: `uv pip install "huggingface-hub<1.0"`. Always use `python3 -m` directly.
- **Query rewriting removed** — `QueryRewriter` class kept in pipeline.py (`ml/eval.py` and `ml/collect_pairs.py` still call `pipeline.rewriter` directly) but NOT called in `forward()`.
- **YouTube URL validation is an exact domain match** — `youtube.py::_is_valid_url()` checks `parsed.netloc.lower()` against a fixed set (`youtube.com`, `youtu.be`, `www.youtube.com`, `m.youtube.com`, `music.youtube.com`), not a substring check. A URL with an unlisted subdomain is rejected even if it "contains" youtube.com.
- **CORS** — `CORSMiddleware` allows `http://localhost:3000` plus any `http://localhost:<port>` via `allow_origin_regex` (dev server may
  fall back to another port). Update for deployment.
- **react-pdf worker** — must use a CDN worker URL matching the exact installed `pdfjs-dist`
  version:
  `https://cdn.jsdelivr.net/npm/pdfjs-dist@{version}/build/pdf.worker.min.mjs`
  Check version: `grep '"version"' frontend/node_modules/pdfjs-dist/package.json`.
  `PDFThumbnail.tsx` instead points at a same-origin `/pdf.worker.min.mjs`.
- **json-repair** — used before `json.loads()` in `graph.py` for robustness against
  malformed LLM JSON output.
- **Context window** — Qwen3 context limit is 40,960 tokens. Auto-compact triggers at
  90% (36,864 tokens) once a session has more than 10 messages, keeps the last 10
  messages, summarizes older ones via `get_model("summarize")` (qwen2.5:3b, direct
  `ollama.chat`, not `generate_stream`).
- **PyMuPDF (`fitz`)** — imported lazily inside `_extract_pdf_text()` in `api/query.py`,
  same lazy-heavy-dep pattern as docling/pdf2image/yt_dlp. Used only for chat
  attachments (fast one-shot text extraction) — ingestion PDFs still go through
  Docling in `ingestion/pdf.py`; these are deliberately two different paths.
- **Attachment temp files** — `/query/with_attachments` writes each upload to a
  temp file before the SSE generator starts (`UploadFile` handles don't survive
  into the generator), and removes them in a `finally` block after streaming ends.
- **Attachments are never ingested** — no ChromaDB writes, no chunking, no
  embedding. Context is prepended to the question string for that turn only;
  follow-up turns retain it because the frontend re-embeds the description into
  each historical message's `content` sent as `history`.
- **Client-disconnect checks** — `/query/stream` and `/query/with_attachments`
  call `await request.is_disconnected()` before each expensive blocking step
  (each attachment, and before generation) so clicking Stop actually halts
  backend work, not just the frontend display.
- **Abort-then-send race** — `useChat.sendMessage()` aborts any in-flight stream
  and awaits a 100ms grace period (and resets `isLoadingRef`) before starting a
  new one, otherwise the previous fetch's reader can throw mid-teardown.
- **pyproject.toml requires Python >=3.13**, but `scripts/install.sh` only enforces
  3.11+ — a 3.11/3.12 environment can pass the install script's check and still
  fail `uv pip install -e .`.
- **`config/paths.py::RERANKER_MODEL_PATH`** (`models/reranker_model.pt`) is not
  currently loaded by `retrieval/reranker.py` — the reranker always loads the base
  HuggingFace checkpoint fresh. `reset_all.sh` deletes this path defensively in
  case a fine-tuned checkpoint is dropped there later.

---

## Infrastructure

```bash
# Activate venv
source .venv/bin/activate

# Start everything (backend + frontend + opens browser)
bash scripts/start.sh

# Full reset
bash scripts/reset_all.sh

# Batch ingest PDFs from data/training_data/
bash scripts/ingest_training_data.sh

# Queue status + recent ingestion log
bash scripts/status.sh
```

---

## API Endpoints
POST /ingest/file multipart: file, source
POST /ingest/url form: url (YouTube only, auto-title via yt-dlp)
POST /ingest/text form: text (auto-title via LLM)
POST /ingest/generate_title form: text → {title}
GET /ingest/status
POST /ingest/clear_completed
POST /ingest/cancel/{job_id}

POST /query full RAG, complete JSON response
POST /query/stream RAG with SSE streaming + stage events
POST /query/direct no RAG, pure Qwen3 SSE stream
POST /query/with_attachments multipart: question, history (JSON), source_filter
  (JSON, optional), is_direct, attachments[] (images/PDFs/text files).
  Same SSE contract as /query/stream, plus a [ATTACHMENTS] event.

GET /documents/
GET /documents/{source}
DELETE /documents/{source}
POST /documents/{source}/check_facts
POST /documents/{source}/check_contradictions

GET /sources/{source}/file serves stored source file (GET + HEAD)

GET /sessions/should_reset one-shot flag consumed after scripts/reset_all.sh runs

POST /title {message} → {title} chat-session title (distinct from /ingest/generate_title)

POST /compact {messages} → {summary} via qwen2.5:3b

GET /settings/user → {user_id, display_name}
POST /settings/telemetry {enabled: bool}
POST /settings/display_name {display_name: str}

GET /health
GET / liveness/status check


**SSE format:**

data: {token}\n\n
data: [STAGE]{"stage": "retrieving_sources|traversing_graph|reranking|generating|processing_attachments"}\n\n
data: [SOURCES]{json}\n\n
data: [ATTACHMENTS]{"attachments": [{"type", "name", "description"}]}\n\n  (attachment query only)
data: [HEARTBEAT]\n\n
data: [DONE]\n\n


---

## Known Gotchas (Frontend)

- **Multi-session chat** — chat state is a list of `ChatSession` objects
  (`useChat`), persisted to `localStorage` under `ragbase_sessions`. The Sidebar
  lists sessions (pinned + recent), supports rename/pin/delete. There is no
  single global conversation — always operate on `activeSession`.
- **Chat session reset** — `GET /sessions/should_reset` is polled once on mount;
  a `true` response (set by `scripts/reset_all.sh`) clears `ragbase_sessions`
  from `localStorage`.
- **PDF preview** — uses react-pdf with CDN worker. `options` prop must be memoized
  with `useMemo` to avoid infinite re-renders. `renderTextLayer={false}` and
  `renderAnnotationLayer={false}` required to avoid react-pdf internal re-render loop.
  Container needs explicit height (e.g. `style={{ height: "65vh" }}`) not `h-full`
  for scrolling to work.
- **Context window bar** — shown in Sidebar footer. Estimates tokens as chars/4 +
  1500 per exchange. Auto-compact at 90% of 40,960 token limit, only once a
  session has more than 10 messages.
- **Source filter** — always visible even with no sources. Shows amber dot for
  graph-pending sources. Passes source_filter to /query/stream only when a
  strict subset of sources is selected; deselecting all sources switches to
  direct mode instead of an empty filter.
- **Stop button** — replaces send button during isLoading || isStreaming.
  AbortController aborts stream, partial content kept.
- **Queue fade-out** — done jobs fade after 30s via fadingJobIds/hiddenJobIds.
  Ingest panel shows the active job queue and File/Text/YouTube ingest tabs;
  completed sources live in the Sources modal only.
- **Cancel button scope** — the X button only shows for "queued"/"ingesting"
  jobs; once a source is "ingested" it's already queryable, so
  "waiting_for_graph"/"building_graph" have no cancel affordance in the panel
  (the Sources modal's delete flow can still cancel + delete a building-graph job).
- **Cancelled jobs hide instantly** — `cancelJob()` adds the id to
  `hiddenJobIds` right away (not a one-off `jobs` filter, which the next
  status poll would just undo) so "Cancelled" never lingers in the queue.
- **Progress animation** — estimated_seconds from backend drives requestAnimationFrame
  easing from 10%→62%. Snaps to 65% on ingested/building_graph, 100% on done.
- **Chat input focus ring** — the blue ring lives only on the outer container
  (`focus-within:border-border/80`); textarea and buttons use `outline-none`
  so no inner element shows its own ring.
- **Attachment paste** — image paste reads `clipboardData.items`; text paste checks
  length against `PASTE_TEXT_THRESHOLD` (5000) — under that pastes normally, over
  that becomes an attachment card via `e.preventDefault()`.
- **Attachment history round-trip** — attachment `description` (VLM output / extracted
  text) is stored on the user `Message`, not re-uploaded on later turns. `useChat`'s
  `historyContent()` folds it back into that message's `content` when building the
  `history` array sent to any query endpoint.
- **PDF page count** — best-effort via a dynamically-imported `pdfjs-dist` in
  `lib/attachments.ts` (kept out of the main bundle); `undefined` if it fails, card
  just omits the page count.
- **Sources modal thumbnails** — lazy-loaded via `IntersectionObserver` in
  `SourceThumbnail`, one HEAD request per card to sniff content-type before
  deciding whether to render a PDF/image/text preview.

---

## Architecture Rationale

- **No query rewriting** — removed (25-30s latency, minimal benefit).
- **Two-phase ingestion** — source queryable immediately after Phase 1.
- **LLM as fallback** — no chunks above threshold → LLM answers from own knowledge.
- **Base reranker** — BGE-Reranker-v2-m3 works well without training.
- **Concise system prompt** — Qwen3 verbose by default.
- **Batch reranking** — all pairs in one GPU forward pass.
- **Dynamic Stage 1** — n_results scales with source count.
- **Direct LLM mode** — empty source selection bypasses RAG pipeline.
- **Graph skip** — has_graph() check before query_related_sources() avoids
  wasted SQLite queries when no graph exists.
- **Embedded ChromaDB** — no Docker needed, simpler distribution, same API.
- **SQLite cache** — replaces Redis, no Docker needed, cross-platform.
- **Anonymous telemetry** — device_id only, no user content ever sent to Pi.
- **Attachments never ingested** — chat attachments (images/PDFs/text) are per-turn
  context only, prepended to the question string; no ChromaDB writes, no chunking.
- **Multi-session chat, client-persisted** — sessions live in `localStorage`
  rather than a backend table, keeping chat history local-only and avoiding a
  new persistence layer for something the browser already handles well.
