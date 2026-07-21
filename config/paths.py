from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

# -- Data -----------------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
CHROMADB_DIR = DATA_DIR / "chromadb"
CACHE_DB_PATH = DATA_DIR / "cache.db"
USER_ID_PATH = DATA_DIR / "user_id.txt"
DEVICE_ID_PATH = DATA_DIR / "device_id.txt"
SETTINGS_JSON_PATH = DATA_DIR / "settings.json"
EVAL_SET_PATH = DATA_DIR / "eval_set.json"
TRAINING_PAIRS_PATH = DATA_DIR / "training_pairs.json"
TRAINING_DATA_DIR = DATA_DIR / "training_data"
QUEUE_STATUS_PATH = DATA_DIR / "queue_status.json"
KNOWLEDGE_GRAPH_DB_PATH = BASE_DIR / "data" / "knowledge_graph.db"
SOURCES_DIR = DATA_DIR / "sources"

# -- Models ---------------------------------------------------------------------
MODELS_DIR = BASE_DIR / "models"
RERANKER_MODEL_PATH = MODELS_DIR / "reranker_model.pt"
