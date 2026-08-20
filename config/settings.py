# -- Infrastructure ------------------------------------------------------------
OLLAMA_URL = "http://localhost:11434"

# -- Telemetry -------------------------------------------------------------------
TELEMETRY_ENABLED = True  # Default only - data/settings.json overrides at runtime

# -- Retrieval -----------------------------------------------------------------
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
TOP_K_CANDIDATES = 20
MAX_FINAL_RESULTS = 5
# Absolute floor in raw BGE logits - -8.0 admitted noise, 0.0 refused too much
RERANKER_MIN_SCORE = -2.0
# The raw-logit range the UI's relevance percentage maps onto linearly
RELEVANCE_SCALE_MIN = -10.0
RELEVANCE_SCALE_MAX = 8.0
SOURCE_PREVIEW_CHARS = 300
# Relative cutoff - drops weak stragglers that clear the floor beside a strong hit
RERANKER_MAX_SCORE_GAP = 5.0
SUMMARY_DISTANCE_THRESHOLD = 0.7  # Stage 1 cosine distance cutoff - above this, off-topic
CACHE_TTL = 86400  # 24 hours in seconds
CACHE_SIMILARITY_THRESHOLD = 0.85
RRF_K = 60

# -- Answer generation ---------------------------------------------------------
# Off because qwen3's reasoning pass dominated latency without improving answers
ANSWER_THINKING_ENABLED = False

# -- Context windows -----------------------------------------------------------
# 24,576 not the 40,960 max - loads are gated on free system RAM, not the GPU
NUM_CTX_STANDARD = 24576
# Smaller than the answer model - 24,576 evicted the query pair mid-graph-build
NUM_CTX_FAST = 16384
# qwen2.5vl needs 7.3 GiB even here and cannot coexist with the query pair
NUM_CTX_VISION = 8192
# bge-m3 has no entry on purpose - a BERT encoder has no generative KV cache to size

# Crossing a window cuts the prompt to ~num_ctx/2 and keeps only this many head tokens
PROMPT_OVERFLOW_KEEP_TOKENS = 4

# -- Explain in depth ----------------------------------------------------------
# 24 chunks is ~18.5k tokens, inside NUM_CTX_STANDARD with room for the answer
EXPLAIN_MAX_CHUNKS = 24
# ~9,200 tokens per batch, inside NUM_CTX_FAST with room for the summary
EXPLAIN_BATCH_CHUNKS = 12
# How often the explain stream emits a keepalive while a batch is still running
EXPLAIN_HEARTBEAT_SECONDS = 10.0

# -- Conversation history ------------------------------------------------------
# Held back from history for the current turn's retrieved chunks
RETRIEVAL_RESERVE_TOKENS = 4096
# Held back for the system prompt and the answer itself, which share the window
ANSWER_RESERVE_TOKENS = 4096
# Matched pair with frontend/lib/config.ts HISTORY_TOKEN_BUDGET - change both or neither
HISTORY_TOKEN_BUDGET = NUM_CTX_STANDARD - RETRIEVAL_RESERVE_TOKENS - ANSWER_RESERVE_TOKENS
# Per-message ceiling so one pasted wall of text cannot consume the whole budget
HISTORY_MESSAGE_MAX_CHARS = 4000

# -- Compaction ----------------------------------------------------------------
# Per-call ceiling for /compact - crossing NUM_CTX_FAST truncates the instruction away
COMPACT_MAX_INPUT_TOKENS = 10000

# -- Ollama residency ----------------------------------------------------------
# Finite rather than -1, so a SIGKILL'd process still releases the memory
OLLAMA_KEEP_ALIVE = "3h"

# Generous because the same gap also covers a cold multi-GB load before the first token
OLLAMA_TIMEOUT_SECONDS = 300

# -- Startup warmup ------------------------------------------------------------
# Only the query-critical group gates the UI. "reranker" is special-cased in main.py
WARMUP_CRITICAL_TASKS = ("embed", "answer", "reranker")
# Empty on purpose - keep the constant, not the contents
WARMUP_BACKGROUND_TASKS = ()
# Per-step ceiling - the frontend gate has no escape, so a hung step would lock it shut
WARMUP_TASK_TIMEOUT_SECONDS = 300

# -- Graph build / query contention --------------------------------------------
GRAPH_YIELD_SLEEP_SECONDS = 0.1
# Caps the total per-chunk wait so a leaked QUERY_IN_PROGRESS cannot stall a build
GRAPH_YIELD_MAX_SECONDS = 60.0
# Drives the progress bar's second half only - a bad estimate never affects the build
GRAPH_SECONDS_PER_CHUNK = 8
# Aborts a build so a wedged Ollama cannot hold the queue one timeout at a time
GRAPH_MAX_CONSECUTIVE_FAILURES = 3

# -- Ingestion queue -----------------------------------------------------------
# How long a finished row stays in the display queue - nothing else removes one
QUEUE_TERMINAL_ROW_TTL_SECONDS = 60

# -- Ingestion -----------------------------------------------------------------
HANDWRITTEN_IMAGE_THRESHOLD = 5
HANDWRITTEN_TEXT_THRESHOLD = 200
# Docling's default 1.0 is too coarse for a VLM to read diagram labels
PDF_IMAGE_SCALE = 2.0

# -- Typed PDF extraction (anydoc) ---------------------------------------------
# Sampled rather than exhaustive so the scanned/typed check stays sub-second
PDF_TEXT_PROBE_PAGES = 20
# Below this many chars per sampled page a PDF is treated as scanned
PDF_SCANNED_CHARS_PER_PAGE = 50
# anydoc buffers the whole file - a 381MB PDF reached 13GB RSS and was OOM-killed
PDF_ANYDOC_MAX_BYTES = 250 * 1024 * 1024
# Typed PDFs finish in seconds, so anything still running here is pathological
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
# Every entry must be a format anydoc can convert - it raises UnsupportedError otherwise
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
