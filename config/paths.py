from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

# The single .env this project reads. Gitignored, optional, and holds exactly one
# key - see the Telemetry block in config/settings.py.
ENV_PATH = BASE_DIR / ".env"

# -- Data -----------------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
CHROMADB_DIR = DATA_DIR / "chromadb"
CACHE_DB_PATH = DATA_DIR / "cache.db"
USER_ID_PATH = DATA_DIR / "user_id.txt"
DEVICE_ID_PATH = DATA_DIR / "device_id.txt"
SETTINGS_JSON_PATH = DATA_DIR / "settings.json"
EVAL_SET_PATH = DATA_DIR / "eval_set.json"
TRAINING_PAIRS_PATH = DATA_DIR / "training_pairs.json"
QUEUE_STATUS_PATH = DATA_DIR / "queue_status.json"
# Batch-ingest corpus: the PDFs and .txt sources metrics/ evaluates against.
# Preserved by scripts/reset_all.sh, unlike everything else under data/.
TRAINING_DATA_DIR = DATA_DIR / "training_data"
KNOWLEDGE_GRAPH_DB_PATH = BASE_DIR / "data" / "knowledge_graph.db"
SOURCES_DIR = DATA_DIR / "sources"

# -- Offline eval harness (metrics/) ---------------------------------------------
METRICS_DIR = BASE_DIR / "metrics"
# Gitignored: the questions and gold chunk indices are authored against one person's
# corpus. The .example is tracked, and `--init` copies it here to start a new set.
QUERY_SET_PATH = METRICS_DIR / "query_set.json"
QUERY_SET_EXAMPLE_PATH = METRICS_DIR / "query_set.example.json"
METRICS_RESULTS_DIR = METRICS_DIR / "results"

# -- Models ---------------------------------------------------------------------
MODELS_DIR = BASE_DIR / "models"
RERANKER_MODEL_PATH = MODELS_DIR / "reranker_model.pt"
