import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from analysis.contradiction import find_contradictions
from analysis.fact_check import check_source_facts
from api.guards import require_finished
from config.logging import setup_logging
from config.paths import SOURCES_DIR
from config.runtime import USER_ID
from config.settings import SOURCE_PREVIEW_CHARS
from ingestion.helpers import delete_source
from ingestion.queue import active_sources, cancel_job, find_active_job
from utils.chromadb_client import get_collection, get_source_chunks

logger = setup_logging(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


class SourceSummary(BaseModel):
    source: str
    chunk_count: int
    flagged_count: int
    contradiction_count: int
    # Extension of the stored original, or "" - the source name is a slug without one
    file_ext: str = ""
    # Opening of chunk 0, shown where there is no previewable original on disk
    preview: str = ""


class ChunkDetail(BaseModel):
    chunk_index: int
    text: str
    flagged: bool
    flag_reason: str
    contradiction: bool
    contradiction_reason: str
    contradicts_source: str


def _stored_extensions() -> dict[str, str]:
    """Map source name -> stored file extension, from one listing of SOURCES_DIR.

    Scanned once per request instead of stat-ing per source: the frontend uses
    this to address files on the Next.js static mount, so getting it here removes
    a per-source HEAD against this server for every card in the sources modal.
    """
    source_dir = SOURCES_DIR / USER_ID
    if not source_dir.exists():
        return {}
    return {path.stem: path.suffix for path in source_dir.iterdir() if path.is_file()}


@router.get("/", response_model=list[SourceSummary])
async def list_documents():
    """List every finished source with summary info.

    Sources with a job in flight are excluded, because their chunk_count is whatever
    has been written so far rather than a final figure.
    """
    collection = get_collection(USER_ID)
    results = await asyncio.to_thread(lambda: collection.get(include=["metadatas"]))
    extensions = await asyncio.to_thread(_stored_extensions)
    in_flight = await asyncio.to_thread(active_sources, USER_ID)
    # Read last - chunk 0 is the authority on existence, so a torn-down source drops out
    first_chunks = await asyncio.to_thread(
        lambda: collection.get(where={"chunk_index": 0}, include=["documents", "metadatas"])
    )

    previews: dict[str, str] = {}
    stored: set[str] = set()
    for text, meta in zip(first_chunks.get("documents") or [], first_chunks.get("metadatas") or []):
        if isinstance(meta, dict) and meta.get("source"):
            stored.add(meta["source"])
            if text:
                previews[meta["source"]] = text[:SOURCE_PREVIEW_CHARS]

    # metadatas can be None on an empty collection in some ChromaDB versions
    metadatas = results.get("metadatas") or []

    sources: dict[str, list[dict]] = {}
    for meta in metadatas:
        if not isinstance(meta, dict):
            continue
        source = meta.get("source")
        if not source or source in in_flight or source not in stored:
            continue
        sources.setdefault(source, []).append(meta)

    summaries = []
    for source, chunks in sources.items():
        summaries.append(
            SourceSummary(
                source=source,
                chunk_count=len(chunks),
                flagged_count=sum(1 for c in chunks if c.get("flagged")),
                contradiction_count=sum(1 for c in chunks if c.get("contradiction")),
                file_ext=extensions.get(source, ""),
                preview=previews.get(source, ""),
            )
        )

    return summaries


@router.get("/{source}", response_model=list[ChunkDetail])
async def get_document(source: str):
    """Get all chunks for a specific source, once its ingestion has finished.

    Gated because chunks are written batch by batch during extraction: without
    this, a request landing mid-job returned whatever had been stored so far as
    though it were the whole document.
    """
    await require_finished(source)

    chunks = await asyncio.to_thread(get_source_chunks, source, USER_ID)

    if not chunks:
        raise HTTPException(status_code=404, detail=f"Source '{source}' not found")

    return [
        ChunkDetail(
            chunk_index=meta.get("chunk_index", 0),
            text=doc,
            flagged=meta.get("flagged", False),
            flag_reason=meta.get("flag_reason", ""),
            contradiction=meta.get("contradiction", False),
            contradiction_reason=meta.get("contradiction_reason", ""),
            contradicts_source=meta.get("contradicts_source", ""),
        )
        for doc, meta in chunks
    ]


@router.delete("/{source}")
async def delete_document(source: str):
    """Delete a source and all its chunks, summary, and graph data."""
    # Cancel first, or the build keeps inserting rows for a source that is gone
    job = await asyncio.to_thread(find_active_job, source, USER_ID)
    if job:
        await asyncio.to_thread(cancel_job, job["id"])
        logger.info(
            f"Cancelled active job '{job['id']}' ({job.get('status')}) to delete '{source}'"
        )

    deleted = await asyncio.to_thread(lambda: delete_source(source, USER_ID))

    # deleted == 0 is not "not found" when a job was just cancelled
    if deleted == 0 and job is None:
        raise HTTPException(status_code=404, detail=f"Source '{source}' not found")

    return {"status": "ok", "deleted": deleted}


@router.post("/{source}/check_facts")
async def check_facts(source: str):
    """Run the factual accuracy checker on a source, once it has finished ingesting."""
    # Gated - grading mid-extraction writes flags onto chunks the job may still delete
    await require_finished(source)

    # One LLM call per chunk - minutes on a large source, all of it off the event loop
    results = await asyncio.to_thread(check_source_facts, source, USER_ID)
    flagged = sum(1 for r in results if r["flagged"])
    return {"status": "ok", "flagged": flagged, "total": len(results)}


@router.post("/{source}/check_contradictions")
async def check_contradictions(source: str):
    """Run contradiction detection on a source against other finished sources."""
    # Gated like check_facts, and this one writes onto both sides of a contradiction
    await require_finished(source)

    # Same reasoning as check_facts: LLM calls plus ChromaDB reads, all synchronous
    count = await asyncio.to_thread(find_contradictions, source, USER_ID)
    return {"status": "ok", "contradictions_found": count}
