from config.logging import setup_logging
from retrieval.embed import embed
from utils.chromadb_client import get_collection
from utils.ollama_client import generate_stream

logger = setup_logging(__name__)


def _check_contradiction(chunk_a: str, chunk_b: str) -> tuple[bool, str]:
    """
    Ask the LLM if two chunks contradict each other on any factual claims.
    Returns (is_contradiction, reason).
    """
    prompt = f"""You are a fact-checking assistant. Compare these two text excerpts and
determine if they contradict each other on any factual claims.

Excerpt A:
{chunk_a}

Excerpt B:
{chunk_b}

Respond in this exact format:
VERDICT: CONTRADICTION or NO_CONTRADICTION
REASON: (explain what contradicts, or "No contradiction found.")

Only flag clear factual contradictions. Different levels of detail or
different perspectives on the same topic are not contradictions."""

    try:
        raw = "".join(generate_stream(prompt))
        verdict = "NO_CONTRADICTION"
        reason = "No contradiction found."

        for line in raw.strip().split("\n"):
            if line.startswith("VERDICT:"):
                verdict = line.replace("VERDICT:", "").strip()
            elif line.startswith("REASON:"):
                reason = line.replace("REASON:", "").strip()

        return verdict == "CONTRADICTION", reason

    except Exception as e:
        logger.error(f"Contradiction check failed: {e}")
        return False, "Contradiction check could not be completed."


def _update_contradiction_flag(
    source: str,
    chunk_index: int,
    is_contradiction: bool,
    reason: str,
    contradicts_source: str,
    user_id: str,
) -> None:
    """Update contradiction metadata for a chunk in ChromaDB."""
    try:
        collection = get_collection(user_id)
        results = collection.get(
            where={"$and": [{"source": source}, {"chunk_index": chunk_index}]},
            include=["metadatas"],
        )
        if not results["ids"]:
            return

        chunk_id = results["ids"][0]
        existing_meta = results["metadatas"][0]
        updated_meta = {
            **existing_meta,
            "contradiction": is_contradiction,
            "contradiction_reason": reason,
            "contradicts_source": contradicts_source,
        }
        collection.update(ids=[chunk_id], metadatas=[updated_meta])

    except Exception as e:
        logger.error(
            f"Failed to update contradiction flag for chunk {chunk_index} of '{source}': {e}"
        )


def find_contradictions(source: str, user_id: str) -> int:
    """
    Compare all chunks from a source against semantically similar chunks
    from other sources. Flags both sides when a contradiction is found.
    Returns the number of contradictions found.
    """
    collection = get_collection(user_id)

    results = collection.get(where={"source": source}, include=["documents", "metadatas"])

    if not results["ids"]:
        logger.warning(f"No chunks found for source '{source}'")
        return 0

    chunks = list(zip(results["documents"], results["metadatas"]))
    contradiction_count = 0

    for doc, meta in chunks:
        chunk_index = meta.get("chunk_index", 0)
        logger.info(
            f"Checking chunk {chunk_index + 1}/{len(chunks)} of '{source}' against other sources..."
        )

        query_embedding = embed(doc)
        similar = collection.query(
            query_embeddings=[query_embedding], n_results=5, include=["documents", "metadatas"]
        )

        similar_docs = similar["documents"][0]
        similar_metas = similar["metadatas"][0]

        for similar_doc, similar_meta in zip(similar_docs, similar_metas):
            if similar_meta.get("source") == source:
                continue

            is_contradiction, reason = _check_contradiction(doc, similar_doc)

            if is_contradiction:
                contradiction_count += 1
                similar_source = similar_meta.get("source", "unknown")
                similar_chunk_index = similar_meta.get("chunk_index", 0)

                logger.info(
                    f"Contradiction found between '{source}' chunk {chunk_index} "
                    f"and '{similar_source}' chunk {similar_chunk_index}"
                )

                _update_contradiction_flag(
                    source, chunk_index, True, reason, similar_source, user_id
                )
                _update_contradiction_flag(
                    similar_source, similar_chunk_index, True, reason, source, user_id
                )

    logger.info(
        f"Contradiction check complete for '{source}': {contradiction_count} contradictions found"
    )
    return contradiction_count
