from rank_bm25 import BM25Okapi

from config.logging import setup_logging
from config.settings import MAX_FINAL_RESULTS, RRF_K, TOP_K_CANDIDATES
from retrieval.embed import embed
from utils.chromadb_client import get_collection, get_summary_collection

logger = setup_logging(__name__)


def search(
    query: str,
    user_id: str,
    n_results: int = MAX_FINAL_RESULTS,
    source_filter: list[str] | None = None,
) -> tuple[list[str], list[dict]]:
    """
    Hybrid search combining BM25 keyword search and vector search
    via Reciprocal Rank Fusion (RRF).

    Returns (docs, metadatas) - the top n_results chunks.
    """
    collection = get_collection(user_id)
    query_embedding = embed(query)

    # Build where filter
    where = _build_filter(user_id, source_filter)

    # Fetch more candidates than needed for reranking
    fetch_n = min(TOP_K_CANDIDATES, collection.count())
    if fetch_n == 0:
        return [], []

    # Vector search
    vector_results = collection.query(
        query_embeddings=[query_embedding],
        n_results=fetch_n,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    docs = vector_results["documents"][0]
    metas = vector_results["metadatas"][0]

    if not docs:
        return [], []

    # BM25 over the vector candidates
    tokenized = [doc.lower().split() for doc in docs]
    bm25 = BM25Okapi(tokenized)
    bm25_scores = bm25.get_scores(query.lower().split())

    # RRF fusion
    fused_scores = _rrf(
        vector_ranks=list(range(len(docs))),
        bm25_ranks=_rank_indices(bm25_scores),
    )

    # Sort by fused score and return top n_results
    sorted_indices = sorted(fused_scores.keys(), key=lambda i: fused_scores[i], reverse=True)
    top_indices = sorted_indices[:n_results]

    return [docs[i] for i in top_indices], [metas[i] for i in top_indices]


def search_summaries(
    query: str,
    user_id: str,
) -> list[str]:
    """
    Stage 1 hierarchical retrieval - search document-level summaries
    to identify which sources are relevant before chunk-level search.

    n_results scales dynamically with collection size: min(max(3, total//3), 8).
    Results with cosine distance > 0.7 are filtered out as irrelevant;
    if all results exceed the threshold, returns the unfiltered list as a fallback.

    Returns a list of relevant source names.
    """
    collection = get_summary_collection(user_id)
    query_embedding = embed(query)

    total_sources = collection.count()
    if total_sources == 0:
        return []

    n_results = min(max(3, total_sources // 3), 8)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(n_results, total_sources),
        include=["metadatas", "distances"],
    )

    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    DISTANCE_THRESHOLD = 0.7
    filtered = [
        meta["source"] for meta, dist in zip(metadatas, distances) if dist <= DISTANCE_THRESHOLD
    ]

    if not filtered:
        filtered = [meta["source"] for meta in metadatas]
        logger.debug(
            f"Stage 1: all {len(metadatas)} results exceeded distance threshold "
            f"{DISTANCE_THRESHOLD} — using unfiltered fallback"
        )

    logger.debug(f"Stage 1 retrieved {len(filtered)} relevant sources: {filtered}")
    return filtered


def _build_filter(user_id: str, source_filter: list[str] | None = None) -> dict | None:
    """Build a ChromaDB where filter for user isolation and optional source filtering."""
    if source_filter and len(source_filter) == 1:
        return {"$and": [{"user_id": user_id}, {"source": source_filter[0]}]}

    if source_filter and len(source_filter) > 1:
        return {"$and": [{"user_id": user_id}, {"source": {"$in": source_filter}}]}

    return {"user_id": user_id}


def _rrf(vector_ranks: list[int], bm25_ranks: list[int], k: int = RRF_K) -> dict:
    """
    Reciprocal Rank Fusion - combine two ranked lists into one score per item.
    Higher score = more relevant.
    """
    scores = {}
    for rank, idx in enumerate(vector_ranks):
        scores[idx] = scores.get(idx, 0) + 1 / (k + rank + 1)
    for rank, idx in enumerate(bm25_ranks):
        scores[idx] = scores.get(idx, 0) + 1 / (k + rank + 1)
    return scores


def _rank_indices(scores: list[float]) -> list[int]:
    """Return indices sorted by score descending."""
    return sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
