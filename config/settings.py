# -- Infrastructure ------------------------------------------------------------
# No .env — all local defaults are hardcoded here.
API_URL = "http://localhost:8001"
OLLAMA_URL = "http://localhost:11434"

# -- Telemetry -------------------------------------------------------------------
# Default only — data/settings.json can override at runtime (see config/runtime.py).
TELEMETRY_ENABLED = True

# -- Retrieval -----------------------------------------------------------------
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
TOP_K_CANDIDATES = 20
MAX_FINAL_RESULTS = 5
# Absolute relevance floor, in raw BGE-reranker logits. It was -8.0, which admitted
# chunks the cross-encoder rates at ~0.1% relevance — the frontend's linear display
# map (lib/utils.ts::relevancePercent) renders -8.0 as "11% match", so the floor sat
# below anything the UI could even show, and those chunks went into the prompt as
# well as the sources panel.
#
# 0.0 is the model's own relevant/not-relevant boundary (sigmoid(0) = 0.5), but it
# sent too many questions down the empty-context path, where the LLM answers from
# its own knowledge with zero citations (see .ai/decisions.md). -2.0 (44% displayed)
# is the deliberate step back from that boundary: still well above the old floor,
# but tolerant of chunks the cross-encoder rates as borderline.
RERANKER_MIN_SCORE = -2.0
# Relative cutoff, applied alongside the floor: drop any chunk more than this many
# logits below the best-scoring chunk in the same result set. Catches the "one
# strong hit plus four weak stragglers" case, where every chunk clears the floor
# but only the leader is actually on topic.
RERANKER_MAX_SCORE_GAP = 5.0
SUMMARY_DISTANCE_THRESHOLD = 0.7  # Stage 1 cosine distance cutoff — above this, source is off-topic
CACHE_TTL = 86400  # 24 hours in seconds
CACHE_SIMILARITY_THRESHOLD = 0.85
RRF_K = 60

# -- Answer generation ---------------------------------------------------------
# qwen3 is a thinking model: it emits a hidden reasoning pass before the answer,
# and on an M3 that pass dominates end-to-end latency. False turns it off via
# Ollama's `think` parameter. Note this is the *only* mechanism that works —
# putting "/no_think" in the prompt is ignored (see §8 of .ai/instructions.md).
ANSWER_THINKING_ENABLED = False

# -- Ollama residency ----------------------------------------------------------
# How long Ollama keeps a *query-critical* model resident after its last use.
# Ollama's own default is 5 minutes, which is shorter than the gap between
# launching the app and asking the first question: warmup finished, the models
# expired, and the first query paid the full multi-GB load inside the request —
# the "first query is slow" bug this replaces.
#
# Deliberately a finite ceiling rather than -1 ("forever"). main.py unloads these
# on shutdown, but that hook only runs for SIGINT/SIGTERM: closing the terminal
# window sends SIGHUP, scripts/start.sh opens by SIGKILLing whatever holds the
# port, and Force Quit/power loss skip it too. A finite TTL self-heals in every
# one of those cases with no reliance on signal handling at all.
#
# Applied at the query-critical call sites only (embed, and the answer model via
# api/query.py::_answer_stream). Ingestion-only models keep Ollama's default TTL
# on purpose — see WARMUP_BACKGROUND_TASKS below for the slot arithmetic.
OLLAMA_KEEP_ALIVE = "3h"

# -- Startup warmup ------------------------------------------------------------
# Models are loaded on startup so the first real request doesn't pay the cold
# start. Warmup runs in the background, but until it finishes it is competing for
# the same GPU as anything the user does, so the UI blocks on it (GET /health
# reports the progress). Only the critical group gates the UI — it is what a
# *query* touches, and it is kept short so the app becomes usable quickly.
# "reranker" is not an Ollama task key; main.py special-cases it.
WARMUP_CRITICAL_TASKS = ("embed", "answer", "reranker")
# Empty on purpose — keep the constant, not the contents.
#
# Ollama holds at most OLLAMA_MAX_LOADED_MODELS runners (3 per GPU by default),
# and warming summarize + qwen2.5vl on top of embed + answer asked for four. The
# measured result on an M3 (2026-08-16, pre-fix): the gate lifted with qwen3 and
# bge-m3 resident, and 8 seconds later — while the background group pulled
# qwen2.5vl onto the GPU — `ollama ps` listed qwen2.5vl and nothing else. Both
# query-critical models were evicted at exactly the moment the UI told the user
# it was ready.
#
# summarize and qwen2.5vl are ingestion-only: nothing on the query path touches
# them, and an ingestion job is already seconds of work, so paying their load on
# demand costs nothing a user notices. Loading them on demand under the default
# 5-minute TTL also means they *release* their slot afterwards, which is what
# keeps total demand inside the budget (2 pinned + 1 ingestion = 3).
WARMUP_BACKGROUND_TASKS = ()
# Per-step ceiling on warmup. The frontend's gate has no "continue anyway" escape,
# so a step that never returns would lock the UI shut forever — marking a step
# finished in a `finally` only covers a step that *raises*, not one that hangs
# (Ollama accepting the connection and going quiet, say). Generous rather than
# tight: a first-ever load pulls several GB off disk.
WARMUP_TASK_TIMEOUT_SECONDS = 300

# -- Graph build / query contention --------------------------------------------
# A graph build is one LLM call per chunk against the same local Ollama process a
# query needs, so between extractions the build pauses while a query is in flight
# (config/runtime.py::QUERY_IN_PROGRESS). GRAPH_YIELD_SLEEP_SECONDS is one pause;
# GRAPH_YIELD_MAX_SECONDS caps the total wait per chunk so a leaked flag can
# never stall a build indefinitely.
GRAPH_YIELD_SLEEP_SECONDS = 0.1
GRAPH_YIELD_MAX_SECONDS = 60.0

# Rough per-chunk cost of the graph build, used only to drive the progress bar's
# second half (the job's estimated_seconds is rewritten with chunk_count * this
# when the graph phase starts). Derived from a measured ~20 minute build over 140
# chunks, yield-to-query pauses included. A bad estimate only means the bar runs
# ahead or falls behind and shimmers — it never affects the build itself.
GRAPH_SECONDS_PER_CHUNK = 8

# -- Ingestion -----------------------------------------------------------------
VISION_TIMEOUT_SECONDS = 180
OLLAMA_VISION_NUM_CTX = 8192
HANDWRITTEN_IMAGE_THRESHOLD = 5
HANDWRITTEN_TEXT_THRESHOLD = 200
# Docling renders embedded PDF images at 72 DPI x this scale. Its default of 1.0 is
# too coarse for a VLM to read labels off a diagram; 2.0 is legible without blowing
# up memory on image-heavy PDFs.
PDF_IMAGE_SCALE = 2.0

# -- Typed PDF extraction (anydoc) ---------------------------------------------
# Number of pages sampled by the PyMuPDF pre-check that decides scanned vs typed.
# Sampling (rather than reading every page) keeps the check under a second on a
# 700-page book.
PDF_TEXT_PROBE_PAGES = 20
# Average extractable characters per sampled page below which a PDF is treated as
# scanned/handwritten and routed to the VLM path. Measured on the training corpus:
# image-only PDFs return 0, typed PDFs return 280-2700.
PDF_SCANNED_CHARS_PER_PAGE = 50
# anydoc buffers the whole PDF in memory. Measured peak RSS is roughly 5x file size
# for normal documents, but a 381MB image-heavy PDF blew past 13GB and was OOM-killed
# by the OS. Anything at or above this goes straight to the Docling fallback, which
# streams page by page.
PDF_ANYDOC_MAX_BYTES = 250 * 1024 * 1024
# Wall-clock ceiling for the anydoc subprocess. Typed PDFs finish in seconds; a job
# still running after this is pathological, so kill it and fall back to Docling.
PDF_ANYDOC_TIMEOUT_SECONDS = 120

# -- Eval ----------------------------------------------------------------------
WANDB_PROJECT = "ragbase"

# -- Embedding/batching -------------------------------------------------------
EMBED_BATCH_SIZE = 64

# -- Chat attachments (ephemeral, never ingested/indexed) ---------------------
ATTACHMENT_TEXT_MAX_CHARS = 8000

# -- Supported file types ------------------------------------------------------
SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tiff"}
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
SUPPORTED_TEXT_EXTENSIONS = {".txt", ".md"}
SUPPORTED_PDF_EXTENSIONS = {".pdf"}
# Handled by ingestion/office.py via anydoc. Every entry here must be a format
# anydoc can convert — it raises UnsupportedError otherwise. .pdf is deliberately
# absent: PDFs keep their own ingestor because they also need the VLM path.
SUPPORTED_OFFICE_EXTENSIONS = {
    ".doc",
    ".docx",
    ".docm",
    ".ppt",
    ".pptx",
    ".pptm",
    ".pps",
    ".ppsx",
    ".ppsm",
    ".pot",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".xlsb",
    ".odt",
    ".ods",
    ".odp",
    ".rtf",
    ".epub",
    ".csv",
}

SUPPORTED_EXTENSIONS = (
    SUPPORTED_PDF_EXTENSIONS
    | SUPPORTED_IMAGE_EXTENSIONS
    | SUPPORTED_VIDEO_EXTENSIONS
    | SUPPORTED_TEXT_EXTENSIONS
    | SUPPORTED_OFFICE_EXTENSIONS
)
