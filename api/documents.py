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
    # Extension of the stored original (".pdf", ".png", ...), or "" if the file is
    # gone. The frontend needs it to build the static /static/sources/... URL,
    # since the source name is a slug with no extension of its own.
    file_ext: str = ""
    # Opening characters of the source's first chunk. The sources modal previews the
    # stored original, which only works for .txt/.md/.csv, images and PDFs - a
    # YouTube transcript has no original at all and an office document's bytes are a
    # ZIP header. Those cases rendered an empty box with a generic icon even though
    # the ingested text was sitting in ChromaDB, so it is carried here.
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
    """List every *finished* source with summary info.

    Sources with a job in flight are excluded. This used to be the raw inventory
    of ChromaDB, deliberately, so the sources modal could show a stuck job and
    let you delete it - but that made every consumer responsible for re-deriving
    "is this actually usable", and each one reported a `chunk_count` that was
    whatever had been written so far, presented as final. Retrieval already
    excludes these sources (`retrieval/search.py::_exclude_clause`), so listing
    them meant offering a document that provably could not answer anything.

    The capability that justified the raw inventory is not lost: in-flight jobs
    come from the ingestion queue, which is where their status and progress
    actually live, and the sources modal renders them from there with a cancel
    control (mirroring SourcesPanel).
    """
    collection = get_collection(USER_ID)
    results = await asyncio.to_thread(lambda: collection.get(include=["metadatas"]))
    extensions = await asyncio.to_thread(_stored_extensions)
    in_flight = await asyncio.to_thread(active_sources, USER_ID)
    # Only chunk 0 of each source, so this stays one small query rather than pulling
    # every chunk's text just to read the first one.
    #
    # Read last on purpose. These reads are four separate points in time, not a
    # snapshot, so a concurrent delete_source() can land between them - and a source
    # that appeared in the metadatas read but has since lost its chunks came back as a
    # phantom: a real chunk_count with an empty preview and an empty file_ext, which the
    # UI rendered as an extra un-previewable card. Chunk 0 exists for every stored
    # source, so making the *last* read the authority on existence means a source torn
    # down mid-call drops out entirely instead of appearing half-built.
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

    # results["metadatas"] can be None when the collection is empty in some
    # ChromaDB versions. Guard against that and skip any malformed entries.
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
    # Stop any in-flight job for this source *before* deleting it. A graph build
    # writes nodes one chunk at a time and holds the SQLite write lock while it
    # does, so deleting underneath a live build both fought that lock and let the
    # build keep inserting rows for a source that no longer exists. The build
    # polls its cancelled status between chunks and abandons the rest.
    #
    # Deliberately here rather than in helpers.delete_source(): the re-ingestion
    # path calls that from inside the very job this would cancel.
    job = await asyncio.to_thread(find_active_job, source, USER_ID)
    if job:
        await asyncio.to_thread(cancel_job, job["id"])
        logger.info(
            f"Cancelled active job '{job['id']}' ({job.get('status')}) to delete '{source}'"
        )

    deleted = await asyncio.to_thread(lambda: delete_source(source, USER_ID))

    # A source still being ingested has no chunks yet, so `deleted == 0` doesn't
    # mean "not found" when we just cancelled its job - the delete did real work.
    if deleted == 0 and job is None:
        raise HTTPException(status_code=404, detail=f"Source '{source}' not found")

    return {"status": "ok", "deleted": deleted}


@router.post("/{source}/check_facts")
async def check_facts(source: str):
    """Run the factual accuracy checker on a source, once it has finished ingesting."""
    # Gated: checking a source mid-extraction would grade a fraction of the
    # document and write `flagged` metadata onto chunks the job may still delete
    # (a failed or cancelled build discards everything).
    await require_finished(source)

    # One LLM call per chunk - minutes on a large source, and it would block the
    # event loop for all of it (no query could even start streaming).
    results = await asyncio.to_thread(check_source_facts, source, USER_ID)
    flagged = sum(1 for r in results if r["flagged"])
    return {"status": "ok", "flagged": flagged, "total": len(results)}


@router.post("/{source}/check_contradictions")
async def check_contradictions(source: str):
    """Run contradiction detection on a source against other finished sources."""
    # Gated for the same reason as check_facts, and with an extra edge: this one
    # compares *across* sources and writes metadata onto both sides of a
    # contradiction, so an unfinished source on either side leaves flags pointing
    # at a document that may not survive its own job.
    await require_finished(source)

    # Same reasoning as check_facts: LLM calls plus ChromaDB reads, all synchronous.
    count = await asyncio.to_thread(find_contradictions, source, USER_ID)
    return {"status": "ok", "contradictions_found": count}
