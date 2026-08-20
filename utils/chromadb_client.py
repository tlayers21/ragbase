import chromadb

from config.logging import setup_logging
from config.paths import CHROMADB_DIR

logger = setup_logging(__name__)

# Shared embedded ChromaDB client - created once per run, reused everywhere
_client = None


def get_client() -> chromadb.ClientAPI:
    """Return the shared embedded ChromaDB client (in-process, persisted to disk)."""
    global _client
    if _client is None:
        logger.info(f"Opening embedded ChromaDB at {CHROMADB_DIR}")
        _client = chromadb.PersistentClient(path=str(CHROMADB_DIR))
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


def get_source_chunks(source: str, user_id: str) -> list[tuple[str, dict]]:
    """Every chunk of one source as (text, metadata), in original document order.

    Chroma returns matches in no meaningful order, so the `chunk_index` metadata
    written at ingest is the only thing that reconstructs the document. Anything
    that reads a whole source - rendering it, fact-checking it, explaining it -
    wants that order, and each caller re-deriving it is how one of them ended up
    iterating a document scrambled.

    Returns [] for an unknown source; callers decide whether that is a 404, a
    warning, or nothing at all.
    """
    collection = get_collection(user_id)
    results = collection.get(where={"source": source}, include=["documents", "metadatas"])

    if not results["ids"]:
        return []

    return sorted(
        zip(results["documents"], results["metadatas"]),
        key=lambda pair: pair[1].get("chunk_index", 0),
    )
