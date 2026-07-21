from config.logging import setup_logging
from config.settings import CHUNK_OVERLAP, CHUNK_SIZE
from utils.ollama_client import embed as _ollama_embed
from utils.ollama_client import embed_batch as _ollama_embed_batch

logger = setup_logging(__name__)


def embed(text: str) -> list[float]:
    """
    Embed a text string using bge-m3 via Ollama.
    This is the single embed function used everywhere in the project -
    ingestion, retrieval, and ML training all import from here.
    """
    return _ollama_embed(text)


def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts using the underlying Ollama client.
    Falls back to parallel per-item embedding if batch isn't supported.

    Exposed here so ingestion and other high-throughput paths can call
    embeddings in batches and reduce RPC/IO overhead.
    """
    return _ollama_embed_batch(texts)


def chunk_text(text: str) -> list[str]:
    """
    Split text into overlapping chunks by word count.
    Uses CHUNK_SIZE and CHUNK_OVERLAP from config.

    Overlap ensures context is not lost at chunk boundaries -
    the last CHUNK_OVERLAP words of each chunk appear again
    at the start of the next chunk.
    """
    if not text or not text.strip():
        return []

    words = text.split()
    chunks = []
    start = 0

    while start < len(words):
        end = start + CHUNK_SIZE
        chunk = " ".join(words[start:end])

        if chunk.strip():
            chunks.append(chunk)

        start += CHUNK_SIZE - CHUNK_OVERLAP

    logger.debug(f"Split {len(words)} words into {len(chunks)} chunks")
    return chunks
