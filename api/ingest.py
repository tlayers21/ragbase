import asyncio
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Form, HTTPException, UploadFile

from config.logging import setup_logging
from config.models import get_model
from config.paths import SOURCES_DIR
from config.runtime import USER_ID
from ingestion.queue import (
    cancel_job,
    clear_completed,
    enqueue,
    enqueue_text,
    enqueue_url,
    get_status,
)
from utils.ollama_client import generate_stream
from utils.text import normalize_title

logger = setup_logging(__name__)
router = APIRouter(prefix="/ingest", tags=["ingest"])


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\s]", "", text.lower())
    return re.sub(r"\s+", "_", text.strip())[:100]


def _save_source_file(source: str, suffix: str, data: bytes) -> None:
    dest_dir = SOURCES_DIR / USER_ID
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / f"{source}{suffix}").write_bytes(data)


@router.post("/file")
async def ingest_file(
    file: UploadFile,
    source: str = Form(...),
    describe_images: bool = Form(False),
):
    """
    Upload a file for ingestion. Returns a job ID immediately.

    `describe_images` is the per-file "Describe diagrams" opt-in and applies to PDFs
    only; every other format ignores it.
    """
    file_bytes = await file.read()
    suffix = Path(file.filename or "").suffix.lower() or ".bin"
    # Uploads run to hundreds of MB (a 381MB PDF is in the test corpus), so both
    # the copy kept in data/sources and the queue's own temp copy are written off
    # the event loop rather than stalling every other request behind the disk.
    await asyncio.to_thread(_save_source_file, source, suffix, file_bytes)
    job_id = await asyncio.to_thread(
        enqueue,
        file_bytes=file_bytes,
        filename=file.filename,
        source=source,
        user_id=USER_ID,
        describe_images=describe_images,
    )
    return {"job_id": job_id, "status": "queued"}


@router.post("/url")
async def ingest_url(
    url: str = Form(...),
):
    """Ingest a YouTube URL. Fetches video title via yt-dlp. Returns a job ID immediately."""

    # Strip timestamp params that can cause yt-dlp to fail (&t=504s or ?t=504s)
    url = re.sub(r"&t=\d+s?", "", url)
    url = re.sub(r"\?t=\d+s?", "", url)

    def _fetch_title() -> str:
        try:
            import yt_dlp

            ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info.get("title", "") or ""
        except Exception:
            return ""

    def _video_id_fallback() -> str:
        try:
            parsed = urlparse(url)
            if "youtu.be" in parsed.netloc:
                return parsed.path.lstrip("/").split("?")[0]
            return parse_qs(parsed.query).get("v", ["youtube_video"])[0]
        except Exception:
            return "youtube_video"

    raw_title = await asyncio.to_thread(_fetch_title)
    source = _slugify(raw_title) if raw_title else ""
    if not source:
        source = _video_id_fallback()

    job_id = enqueue_url(url=url, source=source, user_id=USER_ID)
    return {"job_id": job_id, "status": "queued", "source": source}


@router.post("/text")
async def ingest_text(
    text: str = Form(...),
    source: str = Form(...),
):
    """Ingest raw pasted text. Returns a job ID immediately."""
    await asyncio.to_thread(_save_source_file, source, ".txt", text.encode())
    job_id = await asyncio.to_thread(enqueue_text, text=text, source=source, user_id=USER_ID)
    return {"job_id": job_id, "status": "queued"}


@router.post("/generate_title")
async def generate_title(text: str = Form(...)):
    """Generate a short 2-5 word title for ingested text using the fast LLM."""
    prompt = (
        "Generate a short 2-5 word title for this text. "
        "Reply in English with only the title, as plain words separated by single "
        "spaces. No punctuation, no quotes.\n\n"
        f"{text[:500]}"
    )

    def _call() -> str:
        return "".join(generate_stream(prompt, model=get_model("title"))).strip()

    try:
        title = await asyncio.to_thread(_call)
    except Exception as e:
        logger.warning(f"Title generation failed: {e}")
        title = ""

    return {"title": normalize_title(title)}


@router.get("/status")
async def queue_status():
    """Get current status of all ingestion jobs."""
    # The frontend polls this every 1-3s while anything is active, and it reads a
    # JSON file guarded by _status_lock — which both queue workers also hold. On
    # the event loop, one contended read stalls every in-flight request.
    return {"jobs": await asyncio.to_thread(get_status)}


@router.post("/clear_completed")
async def clear_done():
    """Remove completed jobs from the status list."""
    await asyncio.to_thread(clear_completed)
    return {"status": "ok"}


@router.post("/cancel/{job_id}")
async def cancel_ingestion(job_id: str):
    """Cancel an active ingestion job (queued, ingesting, ingested, or building_graph)."""
    cancelled = await asyncio.to_thread(cancel_job, job_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found or not cancellable")
    return {"status": "ok", "job_id": job_id, "job_status": "cancelled"}
