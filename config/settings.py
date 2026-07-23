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
CACHE_TTL = 86400  # 24 hours in seconds
CACHE_SIMILARITY_THRESHOLD = 0.85
RRF_K = 60

# -- Ingestion -----------------------------------------------------------------
VISION_TIMEOUT_SECONDS = 180
OLLAMA_VISION_NUM_CTX = 8192
HANDWRITTEN_IMAGE_THRESHOLD = 5
HANDWRITTEN_TEXT_THRESHOLD = 200

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

SUPPORTED_EXTENSIONS = (
    SUPPORTED_PDF_EXTENSIONS
    | SUPPORTED_IMAGE_EXTENSIONS
    | SUPPORTED_VIDEO_EXTENSIONS
    | SUPPORTED_TEXT_EXTENSIONS
)
