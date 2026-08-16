"""SQLite-backed semantic query cache at data/cache.db.

Stores retrieval context (not answers) keyed by query embedding - a cache hit
returns previously retrieved chunks for a semantically similar query, and the
caller regenerates a fresh answer. Entries expire after CACHE_TTL (24h).
"""

import json
import sqlite3
import time

import numpy as np

from config.logging import setup_logging
from config.paths import CACHE_DB_PATH
from config.settings import CACHE_SIMILARITY_THRESHOLD, CACHE_TTL

logger = setup_logging(__name__)


# -- Connection ------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB_PATH, timeout=30)  # timeout: queue worker + API contend
    conn.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            embedding BLOB NOT NULL,
            chunks TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    return conn


def _to_array(embedding: list[float] | np.ndarray) -> np.ndarray:
    return np.asarray(embedding, dtype=np.float32)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def get_cached_response(user_id: str, embedding: list[float] | np.ndarray) -> dict | None:
    """
    Check the cache for a semantically similar query for this user.
    Expired rows (older than CACHE_TTL) are purged first. Returns the
    JSON-parsed cached retrieval context, or None on a miss.
    """
    try:
        query_vec = _to_array(embedding)
        with _connect() as conn:
            conn.execute("DELETE FROM cache WHERE created_at < ?", (time.time() - CACHE_TTL,))
            rows = conn.execute(
                "SELECT embedding, chunks FROM cache WHERE user_id = ?", (user_id,)
            ).fetchall()

        best_score, best_chunks = 0.0, None
        for blob, chunks_json in rows:
            cached_vec = np.frombuffer(blob, dtype=np.float32)  # dtype must match _to_array()
            similarity = _cosine_similarity(query_vec, cached_vec)
            if similarity > best_score:
                best_score, best_chunks = similarity, chunks_json

        if best_chunks is not None and best_score >= CACHE_SIMILARITY_THRESHOLD:
            logger.debug(f"Cache hit (similarity={best_score:.3f}) for user '{user_id}'")
            return json.loads(best_chunks)
        return None
    except Exception as e:
        logger.warning(f"Cache lookup failed: {e}")
        return None


def set_cached_response(user_id: str, embedding: list[float] | np.ndarray, chunks: dict) -> None:
    """Store retrieval context for a query embedding. Answers are never cached."""
    try:
        blob = _to_array(embedding).tobytes()
        with _connect() as conn:
            conn.execute(
                "INSERT INTO cache (user_id, embedding, chunks, created_at) VALUES (?, ?, ?, ?)",
                (user_id, blob, json.dumps(chunks), time.time()),
            )
        logger.debug(f"Cached retrieval context for user '{user_id}'")
    except Exception as e:
        logger.warning(f"Cache store failed: {e}")


def clear_cache(user_id: str) -> int:
    """Clear all cached responses for a user. Returns number of entries cleared."""
    try:
        with _connect() as conn:
            cursor = conn.execute("DELETE FROM cache WHERE user_id = ?", (user_id,))
        logger.info(f"Cleared {cursor.rowcount} cache entries for user '{user_id}'")
        return cursor.rowcount
    except Exception as e:
        logger.warning(f"Cache clear failed: {e}")
        return 0
