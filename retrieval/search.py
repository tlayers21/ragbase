from rank_bm25 import BM25Okapi

from config.logging import setup_logging
from config.settings import MAX_FINAL_RESULTS, RRF_K, SUMMARY_DISTANCE_THRESHOLD, TOP_K_CANDIDATES
from ingestion.queue import active_sources
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

    Sources with an in-flight ingestion job are excluded - see `_exclude_clause`.

    Returns (docs, metadatas) - the top n_results chunks.
    """
    collection = get_collection(user_id)
    query_embedding = embed(query)

    # Build where filter
    where = _build_filter(user_id, source_filter, active_sources(user_id))

    # Fetch more candidates than needed for reranking
    fetch_n = min(TOP_K_CANDIDATES, collection.count())  # Chroma errors if n > collection size
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

    # BM25 runs over the vector candidates only (not the full corpus) - cheap
    # keyword re-scoring of an already-relevant pool
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
    Sources with an in-flight ingestion job are excluded - a summary is written
    before the graph build, so without this Stage 1 would nominate a document
    that isn't finished, and the unfiltered fallback would do it unconditionally.

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
        where=_exclude_clause(active_sources(user_id)),
        include=["metadatas", "distances"],
    )

    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    filtered = [
        meta["source"]
        for meta, dist in zip(metadatas, distances)
        if dist <= SUMMARY_DISTANCE_THRESHOLD
    ]

    if not filtered:
        filtered = [meta["source"] for meta in metadatas]
        logger.debug(
            f"Stage 1: all {len(metadatas)} results exceeded distance threshold "
            f"{SUMMARY_DISTANCE_THRESHOLD} - using unfiltered fallback"
        )

    logger.debug(f"Stage 1 retrieved {len(filtered)} relevant sources: {filtered}")
    return filtered


# -- Filter and fusion helpers -----------------------------------------------
def _exclude_clause(excluded: set[str] | None) -> dict | None:
    """
    A `$nin` clause hiding sources whose ingestion job hasn't finished, or None.

    A job stores its chunks and summary in ChromaDB and then spends minutes
    building its knowledge graph, so between those points the source is
    physically searchable while the app considers it unfinished. The frontend
    already keeps it out of the source picker; this is what makes that a real
    guarantee rather than a UI convention - without it an unfiltered question
    still retrieves from a half-built document.

    Returns None when nothing is in flight, which is the overwhelmingly common
    case: an empty `$nin` is not a filter worth sending to Chroma.
    """
    return {"source": {"$nin": sorted(excluded)}} if excluded else None


def _build_filter(
    user_id: str,
    source_filter: list[str] | None = None,
    excluded: set[str] | None = None,
) -> dict | None:
    """Build a ChromaDB where filter for user isolation, optional source
    filtering, and exclusion of sources still being ingested."""
    # ChromaDB requires explicit $and for multi-field filters
    clauses: list[dict] = [{"user_id": user_id}]

    if source_filter and len(source_filter) == 1:
        clauses.append({"source": source_filter[0]})
    elif source_filter:
        clauses.append({"source": {"$in": source_filter}})

    exclude = _exclude_clause(excluded)
    if exclude:
        clauses.append(exclude)

    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


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
