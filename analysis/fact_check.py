from config.logging import setup_logging
from utils.chromadb_client import get_collection
from utils.ollama_client import generate_stream

logger = setup_logging(__name__)


def check_chunk_facts(chunk_text: str) -> tuple[bool, str]:
    """
    Use the fast model (qwen2.5:3b) to fact-check a single chunk against
    general knowledge. Returns (is_flagged, reason).
    """
    prompt = f"""You are a fact-checking assistant. Review the following text and identify
any statements that appear factually incorrect, misleading, or inconsistent with
established knowledge.

Text to review:
{chunk_text}

Respond in this exact format:
VERDICT: OK or FLAGGED
REASON: (if FLAGGED, explain what seems incorrect. If OK, write "No issues found.")

Be conservative - only flag clear factual errors, not opinions or uncertain claims."""

    try:
        raw = "".join(generate_stream(prompt))
        verdict = "OK"
        reason = "No issues found."

        for line in raw.strip().split("\n"):
            if line.startswith("VERDICT:"):
                verdict = line.replace("VERDICT:", "").strip()
            elif line.startswith("REASON:"):
                reason = line.replace("REASON:", "").strip()

        is_flagged = verdict == "FLAGGED"
        return is_flagged, reason

    except Exception as e:
        logger.error(f"Fact check failed: {e}")
        return False, "Fact check could not be completed."


def _update_chunk_flag(
    source: str,
    chunk_index: int,
    flagged: bool,
    reason: str,
    user_id: str,
) -> None:
    """Update fact-check metadata for a chunk in ChromaDB."""
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
            "flagged": flagged,
            "flag_reason": reason,
        }
        collection.update(ids=[chunk_id], metadatas=[updated_meta])

    except Exception as e:
        logger.error(f"Failed to update fact-check flag for chunk {chunk_index} of '{source}': {e}")


def check_source_facts(source: str, user_id: str) -> list[dict]:
    """
    Fact-check all chunks for a source. Stores results back into ChromaDB.
    Returns list of results with verdict and reason per chunk.
    """
    collection = get_collection(user_id)
    results = collection.get(where={"source": source}, include=["documents", "metadatas"])

    if not results["ids"]:
        logger.warning(f"No chunks found for source '{source}'")
        return []

    chunks = sorted(
        zip(results["documents"], results["metadatas"]), key=lambda x: x[1].get("chunk_index", 0)
    )

    flagged_count = 0
    output = []

    for doc, meta in chunks:
        chunk_index = meta.get("chunk_index", 0)
        logger.info(f"Fact checking chunk {chunk_index + 1}/{len(chunks)} of '{source}'...")

        is_flagged, reason = check_chunk_facts(doc)

        if is_flagged:
            flagged_count += 1

        _update_chunk_flag(source, chunk_index, is_flagged, reason, user_id)
        output.append(
            {
                "chunk_index": chunk_index,
                "flagged": is_flagged,
                "reason": reason,
            }
        )

    logger.info(f"Fact check complete for '{source}': {flagged_count}/{len(chunks)} chunks flagged")
    return output
