import chromadb

from config.logging import setup_logging
from config.settings import CHROMA_HOST, CHROMA_PORT

logger = setup_logging(__name__)

# Shared connection to ChromaDB - created once per run, reused everywhere
_client = None


def get_client() -> chromadb.HttpClient:
    """Return the shared ChromaDB client. Connects once, reused everywhere."""
    global _client
    if _client is None:
        logger.info(f"Connecting to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}")
        _client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    return _client


# -- Per-User Collections -------------------------------------------------------
def get_collection(user_id: str) -> chromadb.Collection:
    """Get or create the chunk collection for a user."""
    client = get_client()
    name = f"user_{user_id}"
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},  # HNSW indexing, cosine similarity
    )


def get_summary_collection(user_id: str) -> chromadb.Collection:
    """Get or create the document summary collection for a user.
    Used for stage 1 hierarchical retrieval."""
    client = get_client()
    name = f"user_{user_id}_summaries"
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},  # HNSW indexing, cosine similarity
    )
