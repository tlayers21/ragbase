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
    """Embed a list of texts, falling back to parallel per-item calls if batching fails.

    Exposed here so high-throughput ingestion paths can batch and cut RPC overhead.
    """
    return _ollama_embed_batch(texts)


def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks by word count, using CHUNK_SIZE and CHUNK_OVERLAP.

    The overlap repeats each chunk's tail at the next chunk's head so context survives
    the boundary.
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
