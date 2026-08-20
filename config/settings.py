# -- Infrastructure ------------------------------------------------------------
# No .env - all local defaults are hardcoded here.
API_URL = "http://localhost:8001"
OLLAMA_URL = "http://localhost:11434"

# -- Telemetry -------------------------------------------------------------------
# Default only - data/settings.json can override at runtime (see config/runtime.py).
TELEMETRY_ENABLED = True

# -- Retrieval -----------------------------------------------------------------
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
TOP_K_CANDIDATES = 20
MAX_FINAL_RESULTS = 5
# Absolute relevance floor, in raw BGE-reranker logits. -8.0 admitted chunks rated at
# ~0.1% relevance - below anything the UI could show (relevancePercent renders it as
# "11% match"), and they reached the prompt, not just the sources panel. 0.0, the
# model's own boundary, was too strict the other way: too many questions fell through
# to the empty-context path and answered with no citations. -2.0 displays as 44%.
RERANKER_MIN_SCORE = -2.0
# The raw-logit range the UI's relevance percentage maps onto, linearly: a score of
# RELEVANCE_SCALE_MIN displays as 0% and RELEVANCE_SCALE_MAX as 100%. Named here
# because the settings slider is expressed in that percentage and has to convert
# back, and because a floor at or below the bottom of the scale means "show me
# everything" - see rerank_candidates(). Must stay in step with
# frontend/lib/utils.ts::relevancePercent.
RELEVANCE_SCALE_MIN = -10.0
RELEVANCE_SCALE_MAX = 8.0
# How much of a source's first chunk GET /documents/ carries as a preview, for the
# sources modal to show when there is no previewable original file on disk.
SOURCE_PREVIEW_CHARS = 300
# Relative cutoff, applied alongside the floor: drop any chunk more than this many
# logits below the best-scoring chunk in the same result set. Catches the "one
# strong hit plus four weak stragglers" case, where every chunk clears the floor
# but only the leader is actually on topic.
RERANKER_MAX_SCORE_GAP = 5.0
SUMMARY_DISTANCE_THRESHOLD = 0.7  # Stage 1 cosine distance cutoff - above this, source is off-topic
CACHE_TTL = 86400  # 24 hours in seconds
CACHE_SIMILARITY_THRESHOLD = 0.85
RRF_K = 60

# -- Answer generation ---------------------------------------------------------
# qwen3 is a thinking model: it emits a hidden reasoning pass before the answer,
# and on an M3 that pass dominates end-to-end latency. False turns it off via
# Ollama's `think` parameter. Note this is the *only* mechanism that works -
# putting "/no_think" in the prompt is ignored (see section 8 of .ai/instructions.md).
ANSWER_THINKING_ENABLED = False

# -- Context windows -----------------------------------------------------------
# One window per model, applied to every call through config/models.py::get_num_ctx.
#
# These are not optional tuning knobs. Omit `num_ctx` and Ollama applies its own
# default of **4096** (measured 2026-08-17 via `ollama ps`, not qwen3's native
# 40,960) and then truncates anything longer *silently*. Five reranked chunks is
# already ~3,850 tokens before the system prompt, the history and the answer, so the
# ordinary query path was losing retrieved context with nothing reporting it.
#
# Why these values and not the model maximums. Ollama on this 24GB M3 reports
# `system_limited=true` and gates loads on **free system RAM**, not the GPU - it was
# observed evicting an 8.2 GiB load while 13.4 GiB of the 16 GiB Metal budget was
# free, because only 3.9 GiB of system memory was. Measured `system_free` over a
# working session ranged 3.3-10.5 GiB. Ollama's own predictions for qwen3:
#
#     num_ctx    qwen3    + bge-m3    + qwen2.5:3b (during ingestion)
#       4,096    5.4 GiB    6.5 GiB     8.4 GiB
#      24,576    8.2 GiB    9.3 GiB    12.7 GiB      <- chosen
#      32,768    9.5 GiB   10.6 GiB    13.7 GiB
#      40,960   10.5 GiB   11.6 GiB    14.7 GiB
#
# 40,960 would need 10.5 GiB free at load time - the very top of that range - which
# brings back the pressure-eviction the residency work exists to avoid. 24,576 is 6x
# the old effective window and is already proven to load here.
NUM_CTX_STANDARD = 24576
# qwen2.5:3b stays deliberately smaller than the answer model. Only the answer path
# needed the larger window; nothing here justifies the extra eviction pressure during
# ingestion, and that pressure was measured rather than assumed: at 24,576 this model
# predicts 2.6 GiB against 1.9 at 4096, and loading it with 2.7 GiB of system memory
# free evicted the query pair mid-graph-build.
#
# Not lower, though. The explain map step feeds it batches of EXPLAIN_BATCH_CHUNKS,
# ~9,200 tokens, so Ollama's 4096 default would silently summarize a third of each
# batch and the reduce step would explain a document it had mostly never seen.
#
# Known bound: /compact also runs on this model and can send more than this when a
# conversation compacts at the top of HISTORY_TOKEN_BUDGET. See .ai/decisions.md.
NUM_CTX_FAST = 16384
# qwen2.5vl. Unchanged, and deliberately smaller: it already needs 7.3 GiB here, and
# it is the one model that cannot coexist with the query pair regardless.
NUM_CTX_VISION = 8192
# bge-m3 has no entry on purpose - a BERT encoder has no generative KV cache, and a
# 512-word chunk is ~700 tokens against a 4096 default. Nothing to size.

# -- Explain in depth ----------------------------------------------------------
# "Explain this source" deliberately skips retrieval: ranking exists to pick the few
# chunks that answer a specific question, and this asks about the whole document. So
# the size of a source, not its relevance, is the only limit that applies.
#
# The arithmetic, at CHUNK_SIZE = 512 words: one chunk is roughly 770 tokens. A typical
# source here is ~13 chunks (~10k tokens) and fits whole; the largest measured is 155
# chunks (~119k tokens). So one pass up to EXPLAIN_MAX_CHUNKS, and a map-reduce above it.
#
# 24 chunks is ~18.5k tokens, which leaves room inside NUM_CTX_STANDARD for the prompt
# and the answer itself. These no longer carry their own num_ctx: explain runs in the
# same window as every other answer, which is what keeps clicking Explain from tearing
# down the warmed runner and reloading several GB.
EXPLAIN_MAX_CHUNKS = 24
# Batch size for the map step on oversized sources: ~9,200 tokens per batch, comfortably
# inside NUM_CTX_FAST with room for the instructions and the summary it generates.
EXPLAIN_BATCH_CHUNKS = 12

# -- Ollama residency ----------------------------------------------------------
# How long Ollama keeps a *query-critical* model resident. Ollama's 5-minute default
# is shorter than the gap between launching the app and asking the first question, so
# warmup finished, the models expired, and the first query paid a full multi-GB load -
# the "first query is slow" bug this replaces.
#
# Finite rather than -1 ("forever") on purpose: main.py's shutdown unload only runs for
# SIGINT/SIGTERM, and SIGHUP, start.sh's SIGKILL and Force Quit all skip it. A finite
# TTL self-heals in those cases without relying on signal handling.
#
# Applied at query-critical call sites only (embed, and the answer model via
# _answer_stream). Ingestion-only models keep Ollama's default TTL - see
# WARMUP_BACKGROUND_TASKS below for the slot arithmetic.
OLLAMA_KEEP_ALIVE = "3h"

# Socket timeout for every Ollama call, applied by the shared client in
# utils/ollama_client.py. ollama-python's own default is `timeout=None`, i.e. wait
# forever - which is exactly how a graph build froze mid-chunk and took the single
# ingestion worker with it, since cancellation here is cooperative and a thread
# blocked inside the read never gets to check it.
#
# httpx applies this per socket operation, not to the whole response, so on a
# streamed call it bounds the *gap between tokens* rather than the total duration:
# a long answer streams for as long as it likes, while a stalled stream raises.
# Generous rather than tight because that same gap covers a cold multi-GB model
# load before the first token - the value matches WARMUP_TASK_TIMEOUT_SECONDS,
# which exists for the same reason.
OLLAMA_TIMEOUT_SECONDS = 300

# -- Startup warmup ------------------------------------------------------------
# Models are loaded on startup so the first real request doesn't pay the cold
# start. Warmup runs in the background, but until it finishes it is competing for
# the same GPU as anything the user does, so the UI blocks on it (GET /health
# reports the progress). Only the critical group gates the UI - it is what a
# *query* touches, and it is kept short so the app becomes usable quickly.
# "reranker" is not an Ollama task key; main.py special-cases it.
WARMUP_CRITICAL_TASKS = ("embed", "answer", "reranker")
# Empty on purpose - keep the constant, not the contents.
#
# Ollama holds at most OLLAMA_MAX_LOADED_MODELS runners (3 per GPU by default), and
# warming summarize + qwen2.5vl on top of embed + answer asked for four. Measured on an
# M3 (2026-08-16, pre-fix): the gate lifted with qwen3 and bge-m3 resident, and 8s later
# `ollama ps` listed qwen2.5vl and nothing else - both query-critical models evicted at
# exactly the moment the UI said it was ready.
#
# summarize and qwen2.5vl are ingestion-only, and an ingestion job is already seconds of
# work, so loading them on demand costs nothing a user notices. Under the default
# 5-minute TTL they also *release* their slot, keeping demand inside the budget
# (2 pinned + 1 ingestion = 3).
WARMUP_BACKGROUND_TASKS = ()
# Per-step ceiling on warmup. The frontend's gate has no "continue anyway" escape,
# so a step that never returns would lock the UI shut forever - marking a step
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
# ahead or falls behind and shimmers - it never affects the build itself.
GRAPH_SECONDS_PER_CHUNK = 8

# Consecutive *transport* failures (timeouts, connection errors) that abort a graph
# build. A per-call timeout alone is not enough: with Ollama wedged, a 155-chunk
# source would spend 155 x OLLAMA_TIMEOUT_SECONDS - roughly 13 hours - failing one
# chunk at a time while the single queue worker is held. Three in a row means the
# model is not coming back, so fail the job and let the queue advance. Content
# failures (a chunk whose JSON won't parse) do not count: those are per-chunk and
# genuinely skippable.
GRAPH_MAX_CONSECUTIVE_FAILURES = 3

# -- Ingestion queue -----------------------------------------------------------
# How long a finished row (done / cancelled / error) stays in the display queue before
# get_status() drops it. Nothing else removes one: clear_completed() has no caller, and
# restart recovery only rewrites active rows, so without a TTL a cancelled job sat in the
# UI forever. Long enough to read the outcome, short enough to not accumulate.
QUEUE_TERMINAL_ROW_TTL_SECONDS = 60

# -- Ingestion -----------------------------------------------------------------
VISION_TIMEOUT_SECONDS = 180
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
# anydoc can convert - it raises UnsupportedError otherwise. .pdf is deliberately
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
