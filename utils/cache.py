import hashlib
import json

import numpy as np
import redis

from config.logging import setup_logging
from config.settings import CACHE_SIMILARITY_THRESHOLD, CACHE_TTL, REDIS_HOST, REDIS_PORT

logger = setup_logging(__name__)
CACHE_KEY_PREFIX = "ragbase:query:"
CACHE_INDEX_KEY = "ragbase:query_index"

_redis: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    return _redis


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def get_cached_response(
    query_embedding: list[float],
    user_id: str,
) -> dict | None:
    """
    Check Redis for a semantically similar cached query.
    Returns cached retrieval context (context, sources, scores) or None.
    The answer itself is NOT cached — cache hits regenerate a fresh answer.
    """
    try:
        r = _get_redis()
        index_key = f"{CACHE_INDEX_KEY}:{user_id}"
        cached_keys = r.lrange(index_key, 0, -1)

        for key in cached_keys:
            entry_json = r.get(key)
            if not entry_json:
                continue
            entry = json.loads(entry_json)
            similarity = _cosine_similarity(query_embedding, entry["embedding"])
            if similarity >= CACHE_SIMILARITY_THRESHOLD:
                logger.debug(f"Cache hit (similarity={similarity:.3f}) for key {key}")
                return entry["retrieval"]

        return None
    except Exception as e:
        logger.warning(f"Cache lookup failed: {e}")
        return None


def set_cached_response(
    query: str,
    query_embedding: list[float],
    retrieval: dict,
    user_id: str,
) -> None:
    """
    Store a query's retrieval context (context, sources, scores) in Redis.
    Callers pass the retrieval result dict — the generated answer is excluded
    so cache hits always produce a fresh answer against the new question.
    """
    try:
        r = _get_redis()
        key = f"{CACHE_KEY_PREFIX}{user_id}:{hashlib.md5(query.encode()).hexdigest()}"
        entry = {
            "query": query,
            "embedding": query_embedding,
            "retrieval": retrieval,
        }
        r.set(key, json.dumps(entry), ex=CACHE_TTL)
        index_key = f"{CACHE_INDEX_KEY}:{user_id}"
        r.lpush(index_key, key)
        r.expire(index_key, CACHE_TTL)
        logger.debug(f"Cached retrieval context for query: {query[:50]}")
    except Exception as e:
        logger.warning(f"Cache store failed: {e}")


def clear_cache(user_id: str) -> int:
    """Clear all cached responses for a user. Returns number of entries cleared."""
    try:
        r = _get_redis()
        index_key = f"{CACHE_INDEX_KEY}:{user_id}"
        keys = r.lrange(index_key, 0, -1)
        if keys:
            r.delete(*keys)
        r.delete(index_key)
        logger.info(f"Cleared {len(keys)} cache entries for user '{user_id}'")
        return len(keys)
    except Exception as e:
        logger.warning(f"Cache clear failed: {e}")
        return 0
