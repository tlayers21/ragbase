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
RERANKER_MIN_SCORE = -8.0
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

# -- Graph build / query contention --------------------------------------------
# A graph build is one LLM call per chunk against the same local Ollama process a
# query needs, so between extractions the build pauses while a query is in flight
# (config/runtime.py::QUERY_IN_PROGRESS). GRAPH_YIELD_SLEEP_SECONDS is one pause;
# GRAPH_YIELD_MAX_SECONDS caps the total wait per chunk so a leaked flag can
# never stall a build indefinitely.
GRAPH_YIELD_SLEEP_SECONDS = 0.1
GRAPH_YIELD_MAX_SECONDS = 60.0

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
