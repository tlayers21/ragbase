from config.logging import setup_logging
from utils.chromadb_client import get_collection

logger = setup_logging(__name__)


def parse_verdict(raw: str, default_verdict: str, default_reason: str) -> tuple[str, str]:
    """
    Parse the "VERDICT: ...\\nREASON: ..." response format shared by the
    fact-check and contradiction prompts. Missing lines fall back to the
    provided defaults so a malformed LLM response never flags content.
    """
    verdict = default_verdict
    reason = default_reason
    for line in raw.strip().split("\n"):
        if line.startswith("VERDICT:"):
            verdict = line.replace("VERDICT:", "").strip()
        elif line.startswith("REASON:"):
            reason = line.replace("REASON:", "").strip()
    return verdict, reason


def update_chunk_metadata(source: str, chunk_index: int, updates: dict, user_id: str) -> None:
    """
    Merge analysis-result fields into one chunk's ChromaDB metadata,
    located by (source, chunk_index). Failures are logged, never raised -
    a metadata write must not abort a whole analysis run.
    """
    try:
        collection = get_collection(user_id)
        results = collection.get(
            where={"$and": [{"source": source}, {"chunk_index": chunk_index}]},
            include=["metadatas"],
        )
        if not results["ids"]:
            return

        chunk_id = results["ids"][0]
        updated_meta = {**results["metadatas"][0], **updates}
        collection.update(ids=[chunk_id], metadatas=[updated_meta])
    except Exception as e:
        logger.error(f"Failed to update metadata for chunk {chunk_index} of '{source}': {e}")
