from analysis.common import parse_verdict, update_chunk_metadata
from analysis.progress import AnalysisRun
from config.logging import setup_logging
from config.models import get_model
from ingestion.queue import active_sources
from retrieval.embed import embed
from retrieval.search import _build_filter
from utils.chromadb_client import get_collection, get_source_chunks
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
        raw = "".join(generate_stream(prompt, model=get_model("contradiction")))
        verdict, reason = parse_verdict(raw, "NO_CONTRADICTION", "No contradiction found.")
        return verdict == "CONTRADICTION", reason

    except Exception as e:
        logger.error(f"Contradiction check failed: {e}")
        return False, "Contradiction check could not be completed."


def find_contradictions(source: str, user_id: str, run: AnalysisRun | None = None) -> int:
    """Compare a source's chunks against similar chunks from other sources.

    Up to five model calls per chunk, so this is the slower of the two checks by
    a wide margin. Pass a `run` to publish progress and to make it cancellable;
    without one it runs to completion.

    Flags both sides of a contradiction and returns the number found. A cancelled
    run returns what it found before stopping - the flags it wrote are already in
    ChromaDB.
    """
    # Document order so progress logging follows the document, not Chroma's ordering
    chunks = get_source_chunks(source, user_id)

    if not chunks:
        logger.warning(f"No chunks found for source '{source}'")
        return 0

    if run:
        run.begin(len(chunks))

    # Still needed below: each chunk is queried against every *other* source's chunks
    collection = get_collection(user_id)

    contradiction_count = 0
    checked = 0

    for position, (doc, meta) in enumerate(chunks, start=1):
        # Checked between calls, so a cancel lands within one comparison rather than at once
        if run and run.cancelled:
            logger.info(
                f"Contradiction check for '{source}' cancelled after "
                f"{position - 1}/{len(chunks)} chunks"
            )
            break

        chunk_index = meta.get("chunk_index", 0)
        logger.info(
            f"Checking chunk {position}/{len(chunks)} of '{source}' against other sources..."
        )
        if run:
            run.advance(position, contradiction_count)
        checked = position

        query_embedding = embed(doc)
        # Read per chunk - a job can finish partway through a check that runs for minutes
        similar = collection.query(
            query_embeddings=[query_embedding],
            n_results=5,
            where=_build_filter(user_id, excluded=active_sources(user_id)),
            include=["documents", "metadatas"],
        )

        similar_docs = similar["documents"][0]
        similar_metas = similar["metadatas"][0]

        for similar_doc, similar_meta in zip(similar_docs, similar_metas):
            # Also checked here: one chunk is up to five calls, which is its own long wait
            if run and run.cancelled:
                break

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

                # Flag both sides so each source's detail view shows the conflict
                for side, other, idx in (
                    (source, similar_source, chunk_index),
                    (similar_source, source, similar_chunk_index),
                ):
                    update_chunk_metadata(
                        side,
                        idx,
                        {
                            "contradiction": True,
                            "contradiction_reason": reason,
                            "contradicts_source": other,
                        },
                        user_id,
                    )

    if run:
        run.advance(checked, contradiction_count)

    logger.info(
        f"Contradiction check finished for '{source}': {contradiction_count} found "
        f"across {checked}/{len(chunks)} chunks checked"
    )
    return contradiction_count
