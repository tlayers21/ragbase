import os

from dotenv import load_dotenv

load_dotenv()

# -- Infrastructure ------------------------------------------------------------
API_URL = os.environ["API_URL"]
OLLAMA_URL = os.environ["OLLAMA_URL"]
CHROMA_HOST = os.environ["CHROMA_HOST"]
CHROMA_PORT = int(os.environ["CHROMA_PORT"])
REDIS_HOST = os.environ["REDIS_HOST"]
REDIS_PORT = int(os.environ["REDIS_PORT"])

# -- Retrieval -----------------------------------------------------------------
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
TOP_K_CANDIDATES = 20
MAX_FINAL_RESULTS = 5
RERANKER_MIN_SCORE = -8.0
CACHE_TTL = 86400  # 24 hours in seconds
CACHE_SIMILARITY_THRESHOLD = 0.85
RRF_K = 60
MAX_RETRIEVAL_PASSES = 3

# -- Ingestion -----------------------------------------------------------------
VISION_TIMEOUT_SECONDS = 180
OLLAMA_VISION_NUM_CTX = 8192
HANDWRITTEN_IMAGE_THRESHOLD = 5
HANDWRITTEN_TEXT_THRESHOLD = 200

# -- Eval ----------------------------------------------------------------------
WANDB_PROJECT = "ragbase"

# -- Embedding/batching -------------------------------------------------------
EMBED_BATCH_SIZE = 64

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
