from analysis.common import parse_verdict, update_chunk_metadata
from analysis.progress import AnalysisRun
from config.logging import setup_logging
from config.models import get_model
from utils.chromadb_client import get_source_chunks
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
        raw = "".join(generate_stream(prompt, model=get_model("fact_check")))
        verdict, reason = parse_verdict(raw, "OK", "No issues found.")
        return verdict == "FLAGGED", reason

    except Exception as e:
        logger.error(f"Fact check failed: {e}")
        return False, "Fact check could not be completed."


def check_source_facts(source: str, user_id: str, run: AnalysisRun | None = None) -> list[dict]:
    """Fact-check all chunks for a source, storing results back into ChromaDB.

    One model call per chunk, so this runs for minutes on a large source. Pass a
    `run` to publish progress and to make it cancellable; without one it simply
    runs to completion, which is what the tests and any script want.

    Returns a list of results with a verdict and reason per chunk. A cancelled
    run returns the chunks it got through, not an error - the metadata it wrote
    is already in ChromaDB either way.
    """
    chunks = get_source_chunks(source, user_id)

    if not chunks:
        logger.warning(f"No chunks found for source '{source}'")
        return []

    if run:
        run.begin(len(chunks))

    flagged_count = 0
    output = []

    for position, (doc, meta) in enumerate(chunks, start=1):
        # Checked between calls, so a cancel lands within one chunk rather than at once
        if run and run.cancelled:
            logger.info(
                f"Fact check for '{source}' cancelled after {position - 1}/{len(chunks)} chunks"
            )
            break

        chunk_index = meta.get("chunk_index", 0)
        logger.info(f"Fact checking chunk {position}/{len(chunks)} of '{source}'...")
        if run:
            run.advance(position, flagged_count)

        is_flagged, reason = check_chunk_facts(doc)

        if is_flagged:
            flagged_count += 1

        update_chunk_metadata(
            source, chunk_index, {"flagged": is_flagged, "flag_reason": reason}, user_id
        )
        output.append(
            {
                "chunk_index": chunk_index,
                "flagged": is_flagged,
                "reason": reason,
            }
        )

    if run:
        run.advance(len(output), flagged_count)

    logger.info(
        f"Fact check finished for '{source}': {flagged_count} flagged "
        f"across {len(output)}/{len(chunks)} chunks checked"
    )
    return output
