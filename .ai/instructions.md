# RAGbase — Agent Instructions

Canonical project context. Every statement here was verified against the source on
2026-08-07. If code and this file disagree, the code is right — fix this file
(see `.ai/skills/update-instructions.md`).

---

## 1. What This Is

A personal AI knowledge base. Ingest notes, PDFs, images, video and YouTube links;
chat with all of it; get grounded answers with citations. **Everything runs locally
on personal hardware — no cloud API calls, no API keys, no `.env`.** Built as a
portfolio project targeting ML/systems engineering roles.

**Where compute lives:**

| Machine | Role |
|---|---|
| **Mac (M3)** | *All* compute: Ollama inference, ingestion, FastAPI backend, ChromaDB (embedded, in-process), SQLite graph + cache |
| **Raspberry Pi 5** (Tailscale `100.80.105.44`, user `tlayers21`) | Telemetry sink only — small FastAPI + SQLite at `~/telemetry/`, port 9000. **Zero AI compute, zero RAG logic.** |
| **Next.js frontend** | `localhost:3000`, talks to FastAPI on `localhost:8001` |

**GitHub:** github.com/tlayers21/ragbase
**Python:** `>=3.13`, enforced consistently in both `pyproject.toml` and
`scripts/install.sh`.

---

## 2. Repository Map

Only non-obvious detail is called out — read the file for the rest.

```
ragbase/
├── main.py                  FastAPI app + lifespan. Configures DSPy, starts BOTH queue
│                            workers, fires reranker + model warmup as background tasks
│                            (non-blocking: "RAGbase ready" logs before warmup finishes).
│                            CORS: explicit localhost:3000 + regex http://localhost:\d+.
│                            GET /health and GET / for liveness.
├── config/
│   ├── settings.py          All tunable constants. No .env, no env-var reads.
│   ├── models.py            get_model(task) — THE single source of model routing.
│   ├── paths.py             All filesystem paths. KNOWLEDGE_GRAPH_DB_PATH is
│   │                        data/knowledge_graph.db (not "graph.db").
│   ├── runtime.py           USER_ID/DEVICE_ID (generated once, persisted) +
│   │                        data/settings.json overrides. Atomic writes.
│   └── logging.py           setup_logging(name) — console (INFO) + per-module file (DEBUG)
├── ingestion/
│   ├── base.py              BaseIngestor(ABC). Owns the two-phase pipeline (§5).
│   ├── queue.py             TWO independent single-worker queues (ingestion + graph).
│   ├── helpers.py           transcribe(), describe_image(), vision_with_timeout(),
│   │                        delete_source() (standalone, not a method).
│   ├── pdf.py               Three-way routing: anydoc (typed) / Qwen2.5-VL
│   │                        (scanned, page-level resume) / Docling (fallback).
│   ├── office.py            Word/PowerPoint/Excel/ODF/RTF/EPUB/CSV via anydoc.
│   ├── anydoc_convert.py    Runs anydoc in a child process. Never raises —
│   │                        returns a status the caller falls back from.
│   ├── _anydoc_worker.py    That child process. Not imported; spawned.
│   ├── image.py             PaddleOCR + Qwen2.5-VL, fused by an LLM call.
│   ├── video.py / youtube.py  Whisper; youtube.py adds yt-dlp audio download.
│   └── text.py              .txt/.md files + ingest_string() for pasted text.
├── retrieval/
│   ├── embed.py             embed(), embed_batch(), chunk_text() — single import point.
│   ├── search.py            Hybrid BM25 + vector via RRF; search_summaries() = Stage 1.
│   ├── reranker.py          BGE-Reranker-v2-m3 cross-encoder, batched.
│   ├── graph.py             Entity/relationship extraction + SQLite + NetworkX BFS.
│   └── pipeline.py          DSPy signatures + RAGPipeline + prompt builders.
├── analysis/                fact_check.py, contradiction.py, common.py (shared parsing).
├── api/                     One router per concern — see §7 for exact signatures.
├── ml/                      eval.py, generate_eval.py, collect_pairs.py, finetune_embed.py,
│                            common.py. Offline scripts; not imported by the server.
├── utils/                   chromadb_client.py, ollama_client.py, cache.py, telemetry.py
├── frontend/                Next.js 16 App Router — see §9
├── scripts/                 install.sh, start.sh, reset_all.sh, status.sh,
│                            ingest_training_data.sh, metrics.ipynb
└── data/                    All gitignored except settings.json. Never edit by hand.
```

---

## 3. Coding Conventions

These are rules, not suggestions. Each says exactly what to write.

### Python

1. **Logging** — every module starts with `logger = setup_logging(__name__)`.
   Never `print()`. Never `logging.getLogger()` directly.
2. **Model selection** — always `get_model("<task>")`. Never hardcode `"qwen3"` or
   `"qwen2.5:3b"` at a call site. Adding a task means adding a key to
   `config/models.py`, not a string literal.
3. **`generate_stream()` defaults to the answer model (qwen3).** Any call that should
   run on the fast model MUST pass `model=get_model("summarize")` (or the right task)
   explicitly. Read the call site — do not infer the model from context.
4. **All Ollama traffic goes through `utils/ollama_client.py`.** The two deliberate
   exceptions are DSPy (`dspy.LM`, which owns its own transport) and
   `api/compact.py`, which calls `ollama.chat` directly because it needs a single
   blocking completion, not a stream.
5. **Constants live in `config/settings.py`.** A bare number in application code is a
   bug unless it is genuinely local (e.g. a loop bound).
6. **Atomic writes** for every persisted JSON file: write a temp file, then
   `os.replace()`. See `ingestion/queue.py::_save_status` and
   `config/runtime.py::_save_settings`.
7. **No bare `except:` and no bare `except Exception` without logging.** Catch the
   narrowest type you can and always log with context:
   `logger.error(f"Failed X for '{source}': {e}")`.
8. **Graceful degradation.** One component failing must never kill the pipeline —
   OCR failure returns `""`, reranker load failure returns original order, cache
   failure returns `None`. Follow that pattern.
9. **Timeouts use `concurrent.futures.ThreadPoolExecutor`**, never `signal.alarm()`
   (not thread-safe, POSIX-only). See `helpers.py::vision_with_timeout`.
10. **`sqlite3.connect(..., timeout=30)` everywhere** — the queue worker, graph
    thread and API contend for the same files.
11. **Type hints and a docstring on every public function.** Docstrings explain *why*
    when the *what* isn't obvious from the name.
12. **Imports** grouped stdlib → third-party → local, enforced by ruff isort.
    Heavy per-format dependencies (`docling`, `pdf2image`, `yt_dlp`, `fitz`,
    `paddleocr`) are imported *inside* the function that needs them, with a comment
    saying why — this keeps server startup fast.
13. **Style**: line length 100, double quotes, f-strings, early returns over nesting.
14. **DSPy signatures live only in `retrieval/pipeline.py`.** Import them from there.
15. **`BaseIngestor` subclasses implement `extract_text()` and nothing else.**
    Chunking, embedding, storing, summarizing and graph enqueueing are inherited.
16. **After any Python change:** `ruff format . && ruff check . --fix`.
17. **Run modules as `python3 -m <module>` from the project root**, and always
    `python3 -m uvicorn` (bare `uvicorn` resolves to system Python).

### Frontend

18. **Every API call goes through `frontend/lib/api.ts`.** Never `fetch()` in a
    component or hook. (A violation of this in `SourcesModal.tsx` caused a real bug —
    see §8.)
19. **Never hardcode `localhost:8001`.** Read `DEFAULT_API_URL` from `lib/config.ts`,
    which `lib/api.ts` overrides from localStorage at call time.
20. **Never send `user_id`.** The backend reads it from `data/user_id.txt`.
21. **Shared types live in `types/index.ts`** and are imported as `@/types`.
22. **After any TypeScript change:** `cd frontend && npx tsc --noEmit`.

---

## 4. Model Stack — and why each choice

| Task key | Model | Why this model |
|---|---|---|
| `answer`, `query_rewrite` | **qwen3** | Best local reasoning quality available on an M3. It is a *thinking* model, but the thinking pass is **currently disabled** for answers via `ANSWER_THINKING_ENABLED` — it dominated latency (§8). Still not suitable for the ingestion hot path. Also the default when `generate_stream()` omits `model=`. |
| `summarize`, `title`, `text_cleanup`, `entity_extraction`, `fact_check`, `contradiction` | **qwen2.5:3b** | Non-thinking and ~5× faster. These are all high-volume, low-judgement jobs (one call per page, per chunk, per source) where qwen3's reasoning buys nothing and its latency compounds badly. Non-thinking also means `dspy.Predict` works without `AdapterParseError`. |
| `vision_handwrite`, `vision_diagram`, `vision_simple` | **qwen2.5vl** | Replaced LLaVA — markedly better at handwriting and math notation. **All three keys currently resolve to the same model**; the split exists so routing can diverge later without touching call sites. |
| `embed` | **bge-m3** | 1024-dim, strong multilingual retrieval, runs locally under Ollama. |
| reranking | **BAAI/bge-reranker-v2-m3** | Cross-encoder — it reads (question, chunk) *together* rather than comparing two independent vectors, which is what makes it far more accurate than embedding similarity for final ordering. Loaded from HuggingFace via `transformers`, not Ollama. |
| OCR — standalone images | **PaddleOCR** | Best local printed-text accuracy; used *alongside* the VLM, not instead of it. |
| Typed PDFs, office formats | **anydoc** (`firecrawl-anydoc`) | Not a model — a pure-Rust converter with no ML and no network. Emits clean GFM directly, which is why the anydoc path skips the per-page `TextCleanup` LLM call entirely. Measured on `data/training_data/`: a 696-page PDF in 3.7s and a 224-page PDF in 6.8s, against minutes for Docling. |
| OCR — typed PDFs | **RapidOCR** | Only reachable through the Docling *fallback* now. Pinned explicitly via `ocr_options=RapidOcrOptions()`. Docling's default `ocr_options.kind` is `"auto"`, which resolves to whichever engine is installed — it happened to pick RapidOCR here because `easyocr` isn't installed. Pinning makes that reproducible. |
| Handwritten / scanned PDFs | **qwen2.5vl only** | Traditional OCR fails on handwriting; the VLM transcribes directly, no OCR stage. |

**Removed and must not come back:** llama3.1:8b, llama3.2:3b, llava, nomic-embed-text,
moondream, pix2text, pytesseract, Redis.

`get_model()` raises `ValueError` on an unknown key — that is intentional, so a typo
fails loudly instead of silently defaulting.

---

## 5. How Ingestion Works

Two phases, split so a source becomes **queryable as fast as possible**.

**Which ingestor a file gets** is decided by extension in `queue.py::_worker`:
`.pdf` → `PdfIngestor`; the 20 office/e-book extensions in
`SUPPORTED_OFFICE_EXTENSIONS` → `OfficeIngestor`; then image, video, `.url`, text.

**PDF routing**, in order — `PdfIngestor.extract_text()`:
1. PyMuPDF text probe → below `PDF_SCANNED_CHARS_PER_PAGE`, go to the VLM path.
2. File at or above `PDF_ANYDOC_MAX_BYTES` → Docling fallback.
3. anydoc → `ok` returns Markdown; `ocr_required` goes to the VLM path; anything
   else (crash, timeout, malformed) falls back to Docling.

```
POST /ingest/file
  → save original to data/sources/{user_id}/{source}{ext}
  → queue.enqueue() writes a temp file + appends job (status "queued")
  → returns job_id immediately     ← the HTTP request ends here

ingestion worker thread (one job at a time):
  status "ingesting"
  PHASE 1 (synchronous, blocking the worker)
    extract_text()             ← the only thing subclasses implement
    chunk_text()               ← 512 words, 50-word overlap
    store()                    ← embed in batches of 64, add to ChromaDB
    generate summary           ← qwen2.5:3b, first 2000 chars
    store_summary()            ← into user_{id}_summaries (Stage 1 index)
    status "ingested"          ← SOURCE IS NOW QUERYABLE. Do not wait for "done".
    clear_cache(user_id)       ← new content invalidates every cached retrieval
  PHASE 2 (deferred)
    enqueue_graph_build() → status "waiting_for_graph"

graph worker thread (separate queue, one build at a time):
    status "building_graph"
    extract entities per chunk ← qwen2.5:3b, the slow part
    status "done"
```

**Job statuses:** `queued → ingesting → ingested → waiting_for_graph → building_graph → done`.
Failures become the literal string `"error: <detail>"`; cancellation sets `"cancelled"`.

**Things that will bite you:**

- **"ingested" means done for query purposes.** Only the knowledge-graph augmentation
  is missing after Phase 1. Never block the UI on `"done"`.
- **Re-ingesting wipes first.** `ingest()` checks ChromaDB for the source and calls
  `delete_source()` (chunks + summary + graph + cache) before storing. Deliberately
  skipped for brand-new sources so the graph DELETE path isn't exercised needlessly.
- **Startup reconciliation** resets any job left in an active status back to `"queued"`
  and re-enqueues it — but only if it still has `source`, `user_id` and `tmp_path`;
  otherwise it is dropped with a warning.
- **Duplicate guard**: enqueueing a source that already has an active job returns the
  existing `job_id` instead of starting a second one.
- **Cancellation is cooperative.** `cancel_job()` only flips the status; ingestors call
  `is_cancelled()` at the top of each chunk batch and each page loop and raise
  `IngestionCancelled`. A job stuck inside a single long VLM call keeps running until
  that call returns.

---

## 6. How a Query Works

`POST /query/stream` is the endpoint the UI actually uses.

```
Stage 0  cache check   Only when no source_filter is set. Embeds the question and
         looks for a cached retrieval with cosine ≥ 0.85 (24h TTL). On a hit,
         stages 1-4 are skipped entirely and it jumps straight to generation.
Stage 1  search_summaries()   Which documents are even relevant?
         Searches user_{id}_summaries, n_results = min(max(3, total//3), 8),
         drops cosine distance > SUMMARY_DISTANCE_THRESHOLD (0.7).
         If everything is over threshold, falls back to the unfiltered list.
Stage 2  query_related_sources()   Graph augmentation — only if has_graph().
         Extracts query words (>2 chars), seeds matching nodes, BFS 2 hops,
         adds the sources those nodes came from.
Stage 3  search()   Chunk-level hybrid retrieval within the chosen sources.
         Vector search fetches TOP_K_CANDIDATES (20); BM25 re-scores ONLY that
         pool (not the corpus); RRF (k=60) fuses the two rankings; top 5 returned.
Stage 4  rerank()   BGE cross-encoder scores all pairs in ONE batched forward pass,
         sorts, keeps top 5.
Stage 5  Threshold filter — drop anything below RERANKER_MIN_SCORE (-8.0).
         If nothing survives, context is empty and the LLM answers from its own
         knowledge. No retry, no refusal.
Stage 6  build_answer_prompt() → _answer_stream() on qwen3 with thinking off,
         tokens streamed as SSE.
```

**Source filtering:** the frontend sends `source_filter` only when a *strict subset*
is selected. Deselecting everything switches to `/query/direct` instead of sending an
empty filter. Inside `search_candidates()`, if Stage 1 + graph find nothing within the
filter, it falls back to searching the filtered sources directly.

**Reranker scores are raw unbounded logits (~-10..+8), not probabilities.** Anything
displaying them must normalize first — the frontend applies a sigmoid in
`lib/utils.ts::relevancePercent`.

---

## 7. API Reference

Exact signatures. All request bodies are JSON unless marked `form:` or `multipart:`.

### Ingestion
```
POST   /ingest/file            multipart: file: UploadFile, source: str,
                               describe_images: bool = False  (PDF-only opt-in;
                               every other format ignores it)
                               → {job_id, status: "queued"}
POST   /ingest/url             form: url: str   (YouTube only; title via yt-dlp,
                               &t=/?t= stripped; falls back to video id)
                               → {job_id, status, source}
POST   /ingest/text            form: text: str, source: str → {job_id, status}
POST   /ingest/generate_title  form: text: str → {title}     (document title, qwen2.5:3b)
GET    /ingest/status          → {jobs: [{id, filename, source, user_id, suffix,
                                          tmp_path, estimated_seconds, status}]}
POST   /ingest/clear_completed → {status: "ok"}   (status file only — never data)
POST   /ingest/cancel/{job_id} → {status, job_id, job_status} | 404
```

### Query
```
POST   /query                  {question, history[], source_filter[]|null}
                               → {answer, sources[], scores[]}   NON-STREAMING.
                               Uses the semantic cache. The frontend never calls it.
POST   /query/stream           same body → SSE. The real endpoint the UI uses.
                               Also uses the semantic cache (unless source_filter
                               is set); a hit emits no reranking/graph stage events.
POST   /query/direct           same body → SSE, no retrieval at all.
POST   /query/with_attachments multipart: question: str, history: str (JSON),
                               source_filter: str (JSON), is_direct: str ("true"/"false"),
                               attachments: list[UploadFile] → SSE (+ [ATTACHMENTS])
```

### Documents / sources
```
GET    /documents/             → [{source, chunk_count, flagged_count, contradiction_count}]
GET    /documents/{source}     → [{chunk_index, text, flagged, flag_reason,
                                   contradiction, contradiction_reason, contradicts_source}]
DELETE /documents/{source}     → {status, deleted} | 404
POST   /documents/{source}/check_facts          → {status, flagged, total}
POST   /documents/{source}/check_contradictions → {status, contradictions_found}
GET|HEAD /sources/{source}/file  → the stored original file. Sends Vary: Origin (§8).
```

### Misc
```
GET    /sessions/should_reset  → {reset: bool}   one-shot, consumed on read
POST   /title                  {message} → {title}    (chat session title)
POST   /compact                {messages[]} → {summary}
GET    /settings/user          → {user_id, display_name}
POST   /settings/telemetry     {enabled: bool} → {status, enabled}
POST   /settings/display_name  {display_name: str} → {status, display_name}
GET    /health                 → {status: "ok"}
GET    /                       → {status: "RAGbase API running"}
```

### SSE wire format
```
data: "json-encoded token"\n\n            ← tokens are JSON strings (see §8)
data: [STAGE]{"stage": "retrieving_sources"|"traversing_graph"|"reranking"
                      |"generating"|"processing_attachments"}\n\n
data: [SOURCES]{"sources":[...], "scores":[...], "chunks":[{source,text,score}]}\n\n
data: [ATTACHMENTS]{"attachments":[{type,name,description}]}\n\n
data: [HEARTBEAT]\n\n
data: [DONE]\n\n
```
Control frames keep a bare `[MARKER]` prefix; token frames are JSON, so a payload
starting with `"` is always a token. Empty tokens are skipped server-side.

---

## 8. Known Gotchas

Everything here has bitten someone. Grouped by area.

### SSE / streaming
- **Tokens are JSON-encoded on the wire** (`api/query.py::_sse_token`). A raw `\n`
  inside `data: {token}\n\n` collides with the blank-line frame delimiter, so newline
  tokens were being silently swallowed and every markdown list, heading and paragraph
  collapsed onto one line. If you change the token framing, change both `_sse_token`
  and `consumeQueryStream` in `lib/api.ts`.
- **Never `.trim()` an SSE frame.** Token payloads can be a single space or carry a
  meaningful trailing space; trimming drops them and produces run-together text like
  `"by8 equals96"`. Strip only the line framing.
- **qwen3 streams empty `content` chunks while it is "thinking."** They are filtered
  server-side (`if token:`); without that, ~80% of frames are empty. Thinking is off
  by default now, so this rarely fires — keep the filter anyway, it is the only thing
  standing between a re-enabled `ANSWER_THINKING_ENABLED` and a flood of empty frames.
- **Client-disconnect checks** (`await request.is_disconnected()`) run before each
  expensive blocking step so Stop actually halts backend work. Keep them when editing
  the generators.

### qwen3 thinking
- **`/no_think` in the prompt does nothing here.** It is a Qwen3 soft switch, and
  this Ollama build does not honor it. Measured directly against `ollama.chat`:
  plain prompt → 564 thinking chars; `/no_think` prepended to the *system* prompt →
  **1178** thinking chars and 55% *slower* (the literal text just confuses the
  model); `/no_think` appended to the user message → 621 thinking chars, i.e. no
  effect. Do not reintroduce it in any position.
- **The mechanism that works is Ollama's `think` parameter**, plumbed through
  `generate_stream(..., think=...)` and set from `ANSWER_THINKING_ENABLED` in
  `config/settings.py`. With `think=False` the thinking chars go to exactly 0.
- **It is currently off, and that is a deliberate quality tradeoff.** Measured over
  5 corpus questions on `/query/stream`: mean **80.4s → 34.4s (-57%)**, per-question
  -37% to -72%; direct mode went from tens of seconds to ~2s. Answers stay accurate
  and well grounded, and get shorter (1595 → 1000 mean chars), which actually tracks
  the system prompt's "be concise, 2-3 paragraphs" better. What is lost is
  *structure*: the thinking model reliably produced numbered lists and headings
  where the non-thinking one writes a single prose paragraph. Flip
  `ANSWER_THINKING_ENABLED` back to `True` if that formatting matters more than the
  latency.
- **Every user-facing answer goes through `api/query.py::_answer_stream()`.** There
  are six generation call sites; the helper exists so the thinking toggle and the
  system prompt cannot be applied to five of them and forgotten on the sixth.

### The semantic cache
- Cache stores *retrieval context*, never answers — a hit re-generates the answer
  fresh against the new question, so two phrasings get two answers but share one
  retrieval.
- **Wired into both `POST /query` and `POST /query/stream`.** A hit on the streaming
  path skips stages 1-4 entirely, so the SSE stage sequence goes straight from
  `retrieving_sources` to `generating` with no `traversing_graph`/`reranking` events.
  Any UI that assumes those events always arrive will break.
- **Source-filtered queries bypass the cache entirely** (read *and* write). Cached
  context was built under a different filter, so reusing it would leak chunks from
  sources the user has deselected.
- **Cached entries include `chunks`**, because the citation modal needs the chunk
  text. Entries written before that use `cached.get("chunks", [])` and degrade to no
  citations rather than crashing.
- `clear_cache(user_id)` is called after Phase 1 of every ingest and by
  `delete_source()`, so new content can't be masked by stale retrieval.

### Ingestion — anydoc
- **anydoc runs in a child process, and that is not optional.** It buffers the whole
  document in memory while converting. `data/training_data/Physics II.pdf` (381MB,
  405 pages, image-heavy but *with* a text layer) reached **13.5GB RSS and was
  SIGKILLed** by the OS after 114s. In-process that takes the FastAPI server and the
  ingestion worker down with it. `ingestion/anydoc_convert.py` isolates it so the
  same event is just a non-zero return code, and `PDF_ANYDOC_MAX_BYTES` (250MB)
  stops that file from ever being attempted.
- **The PyMuPDF text probe runs *before* anydoc for the same reason.** anydoc will
  happily buffer a 250MB scanned book just to conclude "OCR is required"; PyMuPDF
  answers the same question from page metadata in well under a second by sampling
  `PDF_TEXT_PROBE_PAGES` (20) pages. Below `PDF_SCANNED_CHARS_PER_PAGE` (50) chars
  per page, the file goes straight to the VLM path.
- **anydoc's `UnsupportedError: ... OCR is required` is the authoritative
  scanned-PDF signal**, and it overrides the probe — a PDF whose text layer is
  nothing but stray page numbers can pass the probe and still need the VLM. Match on
  the string; `_anydoc_worker.py` already does.
- **anydoc output gets no `TextCleanup` pass.** It is already clean GFM (real
  headings, lists, bold), and skipping it removes one qwen2.5:3b call *per page* —
  the single biggest latency win of the switch. The Docling fallback still cleans,
  because its raw `doc.texts` output is fragmented.
- **anydoc returns one blob with no page provenance.** Figure descriptions therefore
  can't be interleaved per page the way the Docling path does it; they are appended
  as a trailing `--- Figures ---` section tagged with the page number.
- **Figure description is opt-in per file** (`describe_images`, the "Describe
  diagrams" checkbox). It requires a Docling layout pass on top of anydoc, which
  erases the speed win — so it defaults to off. PyMuPDF is *not* a substitute:
  `page.get_images()` found **zero** embedded rasters in the training corpus because
  those figures are vector drawings, and vector-op counting flags 100% of pages.
- **CSV becomes a Markdown table**, which is exactly what you want for retrieval —
  the header row survives into every chunk's context.

### Ingestion
- **The queue status file needs `_status_lock`.** Every update is a
  read-modify-write of one shared JSON file from the ingestion worker, the graph
  worker and API threads at once. Two threads writing the same
  `queue_status.json.tmp` meant whichever called `os.replace()` second raised
  `FileNotFoundError`, which killed graph-build callbacks and left the status file
  empty so the UI showed no jobs at all. `_save_status` now uses `mkstemp`, and every
  load-modify-save sequence holds the lock. This was latent for as long as Docling
  took minutes per PDF; anydoc made Phase 1 fast enough to open the window on a
  routine multi-file drop.
- **Embedded PDF images need `generate_picture_images=True`.** Without it,
  `PictureItem.get_image(doc)` returns `None` for *every* picture, so image
  description silently does nothing (verified: a 4-image PDF yielded 0). The
  pipeline options in `pdf.py::extract_text()` set it — don't remove it.
  Historical note: `_describe_images()` used to substitute Docling's
  `<!-- image -->` markdown placeholder, but page text is assembled from
  `doc.texts`, which never contains that marker, so every image was dropped. It now
  keys descriptions by `picture.prov[0].page_no` and interleaves them per page.
- **Docling's default `ocr_options.kind` is `"auto"`**, which silently resolves to
  whichever OCR engine is installed — so the engine could change out from under you
  on a dependency bump. `pdf.py` pins `ocr_options=RapidOcrOptions()` and
  `rapidocr` is a declared dependency. Keep both in sync.
- **`doc.pages` has no text.** Iterate `doc.texts` and read `.prov[0].page_no`.
  `doc.export_to_markdown(page_no=N)` is unreliable.
- **Handwritten detection via `<!-- image -->` ratio** (>5 images with <200 chars, or
  <50 chars per image) still exists but is now only reached inside the Docling
  fallback. The primary detector is the PyMuPDF probe plus anydoc's OCR verdict.
- **Handwritten PDFs resume mid-document** via `data/{source}_progress.json`, written
  after every page. Deleting that file restarts from page 1.
- **Whisper on MPS**: `device="mps"` when available, but `fp16=False` is kept
  regardless of device — Whisper's fp16 path has known MPS bugs.
- **Graph builds are strictly sequential.** A dedicated single-worker queue exists so
  N sources finishing Phase 1 together can't launch N concurrent entity-extraction
  runs against qwen2.5:3b.
- **`_strip_latex()` is lossy by design** — it strips `{}` and `\` globally, which also
  mangles code snippets and embedded JSON. Accepted tradeoff: malformed LaTeX breaks
  JSON generation far more often.

### Storage
- **ChromaDB is embedded** (`PersistentClient(path=data/chromadb/)`) — no server, no
  Docker. Collections are `user_{user_id}` and `user_{user_id}_summaries` (plural).
- **Multi-field Chroma filters need an explicit `{"$and": [...]}`.**
- **Changing the embedding model requires deleting and recreating both collections** —
  bge-m3 is 1024-dim and Chroma will not mix dimensions.
- **Graph tables are per-user and interpolated into SQL** (`nodes_{user_id}`).
  `_validate_user_id()` enforces `^[A-Za-z0-9_]+$` first — never bypass it.
- **SQLite WAL** is enabled on both cache.db and knowledge_graph.db so readers don't
  block the writer.

### Frontend
- **The HTTP cache will poison CORS requests** if the same URL is fetched both as a
  plain `<img src>` (no `Origin` header → no `Access-Control-Allow-Origin` in the
  response) and via `fetch()`. The browser reuses the non-CORS cache entry and the
  fetch fails with a *misleading* "blocked by CORS policy" error on a file that serves
  fine. Fixed on both sides: `/sources/{source}/file` always sends `Vary: Origin`, and
  the `<img>` tags set `crossOrigin="anonymous"`. Keep both.
- **react-pdf**: memoize the `options` prop with `useMemo` or you get an infinite
  re-render loop; pass `renderTextLayer={false}` and `renderAnnotationLayer={false}`;
  give the container an explicit `style={{ height: "65vh" }}` (Tailwind `h-full`
  doesn't work). Worker URL must match the installed `pdfjs-dist` version exactly
  (currently **5.4.296**) — `PDFPreview` uses the jsDelivr CDN, `PDFThumbnail` uses a
  same-origin `/pdf.worker.min.mjs`. Keep both in sync on upgrade.
- **Abort-then-send race**: `useChat.sendMessage()` aborts any in-flight stream, waits
  100ms and resets `isLoadingRef` before starting a new one. Without the grace period
  the old reader throws mid-teardown. Don't remove it.
- **`reader.cancel()` resolves the pending `read()` with `done: true` rather than
  rejecting**, so `consumeQueryStream` must check `signal.aborted` explicitly and
  re-throw — otherwise the caller's AbortError handling never runs.
- **Two `<input type="file">` elements exist on the page** — chat attachments
  (`ACCEPTED_ATTACHMENT_TYPES` from `lib/attachments.ts`) and the ingest dropzone
  (`ACCEPTED_INGEST_TYPES` from `lib/config.ts`). Both now carry an `accept=` filter,
  so target by container, not by presence of the attribute. Drag-and-drop ignores
  `accept` entirely — the backend is still the authority on what it will take.
- **Attachments are never ingested.** No ChromaDB writes, no chunking, no embedding.
  Context is prepended to the question for that turn only; follow-up turns work
  because `useChat.historyContent()` folds the stored `description` back into that
  message's history content.
- **Attachment temp files** are written before the SSE generator starts (UploadFile
  handles don't survive into the generator) and removed in a `finally`.
- **Context window**: qwen3's limit is 40,960 tokens. Auto-compact fires at 90% and
  only once a session has more than 10 messages; it keeps the last 10 and summarizes
  the rest via qwen2.5:3b. Token estimate is `chars/4 + 1500/exchange` — deliberately
  rough.
- **Chat sessions live in `localStorage`** under `ragbase_sessions`, never on the
  backend. `GET /sessions/should_reset` is polled once on mount to honor
  `reset_all.sh`.

### Environment
- **`uv run` / `uv sync` can break the venv** by upgrading huggingface-hub past 1.0,
  which breaks transformers. Fix: `uv pip install "huggingface-hub<1.0"`.
  Prefer `python3 -m` directly. (`pyproject.toml` pins `<1.0`, but a stray
  `uv sync` can still move it.)
- **Never use `uvicorn --reload` during ingestion** — it restarts mid-job and kills
  the worker thread.
- **`config/paths.py::RERANKER_MODEL_PATH` is never loaded.** The reranker always
  pulls the base checkpoint from HuggingFace. `reset_all.sh` deletes that path
  defensively in case a fine-tuned checkpoint is dropped there later.
- **`QueryRewriter` is defined and instantiated but not used in `forward()`.**
  `ml/eval.py` and `ml/collect_pairs.py` still call `pipeline.rewriter` directly, so
  it can't be deleted.
- **YouTube URL validation is an exact netloc match** against a fixed set — an
  unlisted subdomain is rejected even if the string "contains" youtube.com.

---

## 9. Frontend Reference

Next.js **16.2.10** (App Router) · React **19.2.4** · TypeScript strict · Tailwind **v4**.

```
frontend/
├── app/page.tsx          3-panel layout; owns selectedSources + modal state.
│                         isDirectMode = selectedSources.size === 0.
├── app/settings/         display name, API URL, theme, telemetry
├── components/
│   ├── layout/           Sidebar (sessions, context bar), SourcesPanel, ThemeToggle
│   ├── chat/             ChatArea, MessageBubble, ChatInput, SourceFilter, ModelSelector
│   ├── sources/          DropZone, SourcesModal, PDFPreview, PDFThumbnail
│   └── ui/               ConfirmDialog
├── hooks/                useChat, useSources, useIngestion, useSettings
├── lib/                  api.ts, config.ts, attachments.ts, utils.ts
└── types/index.ts        all shared types
```

- **Tailwind v4 is CSS-first** — no `tailwind.config.js`. Theme tokens are declared
  with `@theme inline {}` in `globals.css`. Dark mode uses a custom
  `@variant dark (&:where(.dark, .dark *))` so next-themes' `.dark` class works.
  **Do not use the `dark:` prefix** — CSS variables carry theming.
- **`consumeQueryStream()` is the only SSE parser**, shared by `streamQuery()`,
  `streamDirectQuery()` and `streamAttachmentQuery()`.
- **Ingestion polling interval is dynamic**: 1s while any job is `queued`, 2s while
  `ingesting`, 3s otherwise; polling stops entirely when nothing is active.
- **Done jobs fade after 30s** via `fadingJobIds` → `hiddenJobIds`. Cancelled jobs are
  added to `hiddenJobIds` immediately, because the next poll would otherwise resurrect
  them.
- **`DropZone` owns the "Describe diagrams" checkbox** and passes its value as the
  second argument to `onDrop(files, describeImages)`, which `page.tsx` forwards to
  `uploadFile(file, describeImages)` → `ingestFile()`. It is deliberately local
  component state, not a persisted setting: it is a per-drop decision.
- **Cancel is only offered for `queued`/`ingesting`.** Once `ingested`, the source is
  already usable, so `waiting_for_graph`/`building_graph` have no cancel button in the
  panel (the Sources modal delete flow can still cancel + delete).
- **Focus rings live on the outer container only** (`focus-within:` on the wrapper);
  inner textarea/buttons use `outline-none`, so the input renders as one focus target
  instead of nested rings.

---

## 10. Architecture Decisions

Each of these was a real tradeoff, not an accident.

- **Local-first, no cloud** — the entire premise. Personal notes never leave the
  machine, there is no API bill, and it works offline. Cost: bounded by what an M3
  can run, which drives nearly every other decision here.
- **Embedded ChromaDB over server mode** — no Docker, no daemon, no port, no
  connection lifecycle. Distribution becomes "clone and run." Cost: single-process
  only, so the API and ingestion worker must share one client.
- **SQLite cache over Redis** — same reasoning: removing Redis removed a Docker
  dependency for something a local file does adequately at this scale.
- **anydoc as the primary extractor, Docling as the fallback** — anydoc is two to
  three orders of magnitude faster on typed PDFs and needs no LLM cleanup, but it is
  a text converter: no OCR, no layout model, no figure detection. Docling stays for
  the files anydoc declines (over the memory ceiling, or a crashed/timed-out
  conversion) and is the only thing that can find figures. Cost: both dependencies
  stay installed, and the two paths produce differently-shaped text for the same PDF.
- **Two-phase ingestion** — entity extraction over every chunk is by far the slowest
  step. Deferring it means a document is searchable in seconds instead of minutes; the
  graph just improves recall once it lands.
- **Sequential graph queue** — parallel builds all hammer the same local qwen2.5:3b,
  which is a single process. Concurrency made it slower, not faster.
- **Hybrid BM25 + vector over pure vector** — embeddings miss exact identifiers
  (error codes, proper nouns, symbols); BM25 catches them. Running BM25 only over the
  vector candidate pool keeps it cheap while recovering most of the benefit.
- **RRF over score blending** — vector distances and BM25 scores are on incomparable
  scales, so blending needs tuned weights per corpus. RRF only uses *rank*, so it
  needs no calibration and is stable across very different corpora.
- **Cross-encoder reranking** — bi-encoder retrieval is fast but scores the question
  and chunk independently. The cross-encoder reads them jointly and fixes ordering.
  Applying it to only ~20 candidates keeps the quadratic cost affordable.
- **Base reranker, no fine-tuning** — BGE-Reranker-v2-m3 was good enough out of the
  box that a training loop wasn't justified. `ml/collect_pairs.py` exists for if that
  changes.
- **Hierarchical Stage 1** — searching summaries first narrows chunk search to
  plausible documents, which matters more as the corpus grows. `n_results` scales with
  collection size so a 3-document library isn't over-filtered.
- **LLM fallback instead of refusal** — when nothing clears the rerank threshold the
  model answers from its own knowledge. A useful answer beats "I don't know," and the
  UI shows zero citations so the user can tell the difference.
- **Direct mode** — deselecting all sources bypasses retrieval entirely, turning the
  app into a plain local chat client with near-instant responses.
- **DSPy for structured extraction** — typed signatures with declared input/output
  fields beat hand-rolled prompt strings plus regex parsing for `TextCleanup` and
  `TranscriptionRefinement`. Generation is deliberately *not* DSPy: `dspy.Predict`
  doesn't stream token-by-token, so user-facing answers use `generate_stream()` with a
  prompt built to mirror the signature.
- **`dspy.Predict` not `ChainOfThought`** — the fast model is non-thinking, so an
  explicit reasoning field just wastes tokens.
- **Client-persisted chat sessions** — keeps history local-only and avoids adding a
  persistence layer for something the browser already does well. Cost: history doesn't
  follow you across browsers.
- **Anonymous telemetry** — `device_id` only, never `user_id`, never content.
  Fire-and-forget on a daemon thread with a 2s timeout so an unreachable Pi cannot
  slow down or break a request.
- **No query rewriting** — it added 25-30s of latency for marginal retrieval gain and
  was removed from `forward()`.
- **Answers generated without qwen3's thinking pass** — the reasoning pass was over
  half of end-to-end query latency (80.4s → 34.4s with it off; direct mode ~2s) and
  the answers it produced were not more *correct*, only more elaborately formatted.
  For a knowledge base where the retrieved context already carries the facts, paying
  45 seconds per query for nicer bullet points is the wrong trade. Cost: answers are
  flatter prose and occasionally skip structure a list would have suited. Reversible
  in one constant, `ANSWER_THINKING_ENABLED`.

---

## 11. Infrastructure

```bash
source .venv/bin/activate          # venv is uv-managed at .venv/

bash scripts/install.sh --dry-run  # audit setup: runs every check, changes nothing
bash scripts/start.sh              # update check + backend + frontend + opens browser
bash scripts/reset_all.sh          # wipe chromadb, graph, cache, queue, sources, logs
bash scripts/status.sh             # queue status + tail of ingestion log
bash scripts/ingest_training_data.sh   # batch-ingest every PDF in data/training_data/

# Iterating (skips start.sh's git pull + production build):
python3 -m uvicorn main:app --port 8001
cd frontend && npm run dev
```

`start.sh` checks GitHub for upstream commits and `git pull`s if behind, then rebuilds
the frontend only when its source hash changed. For test/dev loops, start the two
processes directly instead.
