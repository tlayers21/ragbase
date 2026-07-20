import json
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile

from config.logging import setup_logging
from config.paths import DATA_DIR, SOURCES_DIR
from ingestion.queue import (
    cancel_job,
    clear_completed,
    enqueue,
    enqueue_text,
    enqueue_url,
    get_status,
)

logger = setup_logging(__name__)
router = APIRouter(prefix="/ingest", tags=["ingest"])


def _read_progress(source: str) -> dict:
    """Read last_page / pages_total from the ingestion progress file if it exists."""
    progress_file = DATA_DIR / f"{source}_progress.json"
    logger.debug(f"Reading progress file: {progress_file}")
    if not progress_file.exists():
        return {}
    try:
        with open(progress_file) as f:
            data = json.load(f)
        pages_total = data.get("pages_total")
        last_page = data.get("last_page")
        if pages_total and last_page is not None:
            return {"pages_done": max(0, last_page), "pages_total": pages_total}
    except Exception:
        pass
    return {}


def _save_source_file(user_id: str, source: str, suffix: str, data: bytes) -> None:
    dest_dir = SOURCES_DIR / user_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / f"{source}{suffix}").write_bytes(data)


@router.post("/file")
async def ingest_file(
    file: UploadFile,
    source: str = Form(...),
    user_id: str = Form(...),
):
    """Upload a file for ingestion. Returns a job ID immediately."""
    file_bytes = await file.read()
    suffix = Path(file.filename or "").suffix.lower() or ".bin"
    _save_source_file(user_id, source, suffix, file_bytes)
    job_id = enqueue(
        file_bytes=file_bytes,
        filename=file.filename,
        source=source,
        user_id=user_id,
    )
    return {"job_id": job_id, "status": "queued"}


@router.post("/url")
async def ingest_url(
    url: str = Form(...),
    source: str = Form(...),
    user_id: str = Form(...),
):
    """Ingest a YouTube or video URL. Returns a job ID immediately."""
    job_id = enqueue_url(url=url, source=source, user_id=user_id)
    return {"job_id": job_id, "status": "queued"}


@router.post("/text")
async def ingest_text(
    text: str = Form(...),
    source: str = Form(...),
    user_id: str = Form(...),
):
    """Ingest raw pasted text. Returns a job ID immediately."""
    _save_source_file(user_id, source, ".txt", text.encode())
    job_id = enqueue_text(text=text, source=source, user_id=user_id)
    return {"job_id": job_id, "status": "queued"}


@router.get("/status")
async def queue_status():
    """Get current status of all ingestion jobs, with page-level progress where available."""
    jobs = get_status()
    enriched = []
    for job in jobs:
        job_out = dict(job)
        if job.get("status") in {"ingesting", "ingested"} and job.get("source"):
            job_out.update(_read_progress(job["source"]))
        enriched.append(job_out)
    return {"jobs": enriched}


@router.post("/clear_completed")
async def clear_done():
    """Remove completed jobs from the status list."""
    clear_completed()
    return {"status": "ok"}


@router.post("/cancel/{job_id}")
async def cancel_ingestion(job_id: str):
    """Cancel an active ingestion job (queued, ingesting, ingested, or building_graph)."""
    cancelled = cancel_job(job_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found or not cancellable")
    return {"status": "ok", "job_id": job_id, "job_status": "cancelled"}
