from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

# -- Data -----------------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
EVAL_SET_PATH = DATA_DIR / "eval_set.json"
TRAINING_PAIRS_PATH = DATA_DIR / "training_pairs.json"
TRAINING_DATA_DIR = DATA_DIR / "training_data"
QUEUE_STATUS_PATH = DATA_DIR / "queue_status.json"
KNOWLEDGE_GRAPH_DB_PATH = BASE_DIR / "data" / "knowledge_graph.db"
SOURCES_DIR = DATA_DIR / "sources"

# -- Models ---------------------------------------------------------------------
MODELS_DIR = BASE_DIR / "models"
RERANKER_MODEL_PATH = MODELS_DIR / "reranker_model.pt"
