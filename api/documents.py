import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from analysis.contradiction import find_contradictions
from analysis.fact_check import check_source_facts
from config.logging import setup_logging
from config.runtime import USER_ID
from ingestion.helpers import delete_source
from utils.chromadb_client import get_collection

logger = setup_logging(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


class SourceSummary(BaseModel):
    source: str
    chunk_count: int
    flagged_count: int
    contradiction_count: int


class ChunkDetail(BaseModel):
    chunk_index: int
    text: str
    flagged: bool
    flag_reason: str
    contradiction: bool
    contradiction_reason: str
    contradicts_source: str


@router.get("/", response_model=list[SourceSummary])
async def list_documents():
    """List all sources with summary info."""
    collection = get_collection(USER_ID)
    results = await asyncio.to_thread(lambda: collection.get(include=["metadatas"]))

    # results["metadatas"] can be None when the collection is empty in some
    # ChromaDB versions. Guard against that and skip any malformed entries.
    metadatas = results.get("metadatas") or []

    sources: dict[str, list[dict]] = {}
    for meta in metadatas:
        if not isinstance(meta, dict):
            continue
        source = meta.get("source")
        if not source:
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
            )
        )

    return summaries


@router.get("/{source}", response_model=list[ChunkDetail])
async def get_document(source: str):
    """Get all chunks for a specific source."""
    collection = get_collection(USER_ID)
    results = await asyncio.to_thread(
        lambda: collection.get(where={"source": source}, include=["documents", "metadatas"])
    )

    if not results["ids"]:
        raise HTTPException(status_code=404, detail=f"Source '{source}' not found")

    chunks = sorted(
        zip(results["documents"], results["metadatas"]), key=lambda x: x[1].get("chunk_index", 0)
    )

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
    deleted = await asyncio.to_thread(lambda: delete_source(source, USER_ID))

    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"Source '{source}' not found")

    return {"status": "ok", "deleted": deleted}


@router.post("/{source}/check_facts")
async def check_facts(source: str):
    """Run the factual accuracy checker on a source."""
    results = check_source_facts(source, USER_ID)
    flagged = sum(1 for r in results if r["flagged"])
    return {"status": "ok", "flagged": flagged, "total": len(results)}


@router.post("/{source}/check_contradictions")
async def check_contradictions(source: str):
    """Run contradiction detection on a source against other sources."""
    count = find_contradictions(source, USER_ID)
    return {"status": "ok", "contradictions_found": count}
