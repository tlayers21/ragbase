import json
import os
import queue
import tempfile
import threading
import uuid
from pathlib import Path

from config.logging import setup_logging
from config.paths import QUEUE_STATUS_PATH
from config.settings import (
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_PDF_EXTENSIONS,
    SUPPORTED_TEXT_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
)

logger = setup_logging(__name__)


_queue = queue.Queue()
_worker_thread = None

_ACTIVE_STATUSES = {"queued", "ingesting", "ingested", "building_graph"}


# -- Status file helpers ---------------------------------------------------
def _load_status() -> list:
    if not QUEUE_STATUS_PATH.exists():
        return []
    try:
        with open(QUEUE_STATUS_PATH, "r") as f:
            content = f.read().strip()
            return json.loads(content) if content else []
    except json.JSONDecodeError:
        return []


def _save_status(status: list) -> None:
    """Atomic write to prevent corruption on shutdown."""
    tmp = str(QUEUE_STATUS_PATH) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(status, f)
    os.replace(tmp, QUEUE_STATUS_PATH)


def _update_job(job_id: str, new_status: str) -> None:
    status = _load_status()
    for job in status:
        if job["id"] == job_id:
            job["status"] = new_status
            break
    _save_status(status)


def _find_active_job(source: str, user_id: str) -> dict | None:
    """Find an already active job for the same source and user."""
    for job in _load_status():
        if (
            job.get("source") == source
            and job.get("user_id") == user_id
            and job.get("status") in _ACTIVE_STATUSES
        ):
            return job
    return None


def _add_job(job: dict) -> None:
    status = _load_status()
    job_record = {**job, "status": "queued"}
    status.append(job_record)
    _save_status(status)


def _requeue_recovered_jobs() -> int:
    """Recover queued jobs from disk after a restart."""
    status = _load_status()
    recovered = 0
    changed = False

    for job in status:
        job_status = job.get("status")
        if job_status in {"queued", "processing", "ingesting", "ingested", "building_graph"}:
            if job_status != "queued":
                job["status"] = "queued"
                changed = True

            if not job.get("source") or not job.get("user_id") or "tmp_path" not in job:
                logger.warning(f"Skipping unrecoverable queued job '{job.get('id')}' after restart")
                continue

            _queue.put(job)
            recovered += 1

    if changed:
        _save_status(status)

    return recovered


# -- Worker ----------------------------------------------------------------
def _worker():
    """Background thread that processes ingestion jobs one at a time."""
    while True:
        job = _queue.get()
        if job is None:
            break

        job_id = job["id"]
        source = job["source"]
        user_id = job["user_id"]
        suffix = job["suffix"]
        tmp_path = job["tmp_path"]

        _update_job(job_id, "ingesting")
        logger.info(f"Ingesting job '{source}' ({suffix}) for user '{user_id}'")

        try:
            # Ingestors are imported lazily here (not at module top) so their
            # heavy per-format dependencies (docling, paddleocr, whisper,
            # yt-dlp) only load when a job of that type is actually processed.
            if suffix in SUPPORTED_PDF_EXTENSIONS:
                from ingestion.pdf import PdfIngestor

                ingestor = PdfIngestor(user_id, job_id=job_id)
                ingestor.ingest(tmp_path, source)

            elif suffix in SUPPORTED_IMAGE_EXTENSIONS:
                from ingestion.image import ImageIngestor

                ingestor = ImageIngestor(user_id, job_id=job_id)
                ingestor.ingest(tmp_path, source)

            elif suffix in SUPPORTED_VIDEO_EXTENSIONS:
                from ingestion.video import VideoIngestor

                ingestor = VideoIngestor(user_id, job_id=job_id)
                ingestor.ingest(tmp_path, source)

            elif suffix == ".url":
                from ingestion.youtube import YoutubeIngestor

                ingestor = YoutubeIngestor(user_id, job_id=job_id)
                ingestor.ingest(tmp_path, source)

            elif suffix in SUPPORTED_TEXT_EXTENSIONS:
                from ingestion.text import TextIngestor

                ingestor = TextIngestor(user_id, job_id=job_id)
                if job.get("is_string"):
                    ingestor.ingest_string(tmp_path, source)
                else:
                    ingestor.ingest(tmp_path, source)

            else:
                raise ValueError(f"Unsupported file type: {suffix}")

        except Exception as e:
            logger.error(f"Job '{source}' failed: {e}")
            _update_job(job_id, f"error: {e}")

        finally:
            if suffix != ".url" and not job.get("is_string"):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            _queue.task_done()


# -- Public API ------------------------------------------------------------
def start() -> None:
    """Start the background worker thread. Call once on app startup."""
    global _worker_thread
    started_worker = False
    if _worker_thread is None or not _worker_thread.is_alive():
        _worker_thread = threading.Thread(target=_worker, daemon=True)
        _worker_thread.start()
        logger.info("Ingestion queue worker started")
        started_worker = True

    if started_worker:
        recovered = _requeue_recovered_jobs()
        if recovered:
            logger.info(f"Recovered {recovered} queued ingestion jobs after startup")


def enqueue(
    file_bytes: bytes,
    filename: str,
    source: str,
    user_id: str,
) -> str:
    """
    Add a file to the ingestion queue. Saves file to a temp location
    and returns the job ID. The worker processes it in the background.
    """
    suffix = Path(filename).suffix.lower()
    existing = _find_active_job(source, user_id)
    if existing:
        logger.warning(
            f"Skipping duplicate enqueue for source '{source}' and user '{user_id}' "
            f"because job '{existing['id']}' is already active ({existing.get('status')})"
        )
        return existing["id"]

    job_id = str(uuid.uuid4())

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    job = {
        "id": job_id,
        "filename": filename,
        "source": source,
        "user_id": user_id,
        "suffix": suffix,
        "tmp_path": tmp_path,
    }

    _add_job(job)
    _queue.put(job)

    logger.info(f"Enqueued '{filename}' as '{source}' for user '{user_id}'")
    return job_id


def enqueue_url(url: str, source: str, user_id: str) -> str:
    """
    Add a YouTube or video URL to the ingestion queue.
    Returns the job ID.
    """
    existing = _find_active_job(source, user_id)
    if existing:
        logger.warning(
            f"Skipping duplicate enqueue for source '{source}' and user '{user_id}' "
            f"because job '{existing['id']}' is already active ({existing.get('status')})"
        )
        return existing["id"]

    job_id = str(uuid.uuid4())

    job = {
        "id": job_id,
        "filename": source,
        "source": source,
        "user_id": user_id,
        "suffix": ".url",
        "tmp_path": url,
    }

    _add_job(job)
    _queue.put(job)

    logger.info(f"Enqueued URL '{url}' as '{source}' for user '{user_id}'")
    return job_id


def enqueue_text(text: str, source: str, user_id: str) -> str:
    """
    Add a raw text string to the ingestion queue.
    Returns the job ID.
    """
    existing = _find_active_job(source, user_id)
    if existing:
        logger.warning(
            f"Skipping duplicate enqueue for source '{source}' and user '{user_id}' "
            f"because job '{existing['id']}' is already active ({existing.get('status')})"
        )
        return existing["id"]

    job_id = str(uuid.uuid4())

    job = {
        "id": job_id,
        "filename": source,
        "source": source,
        "user_id": user_id,
        "suffix": ".txt",
        "tmp_path": text,
        "is_string": True,
    }

    _add_job(job)
    _queue.put(job)

    logger.info(f"Enqueued text '{source}' for user '{user_id}'")
    return job_id


def cancel_job(job_id: str) -> bool:
    """Mark an active job as cancelled. Returns True if the job was found and cancellable."""
    status = _load_status()
    found = False
    for job in status:
        if job["id"] == job_id and job.get("status") in _ACTIVE_STATUSES:
            job["status"] = "cancelled"
            found = True
            break
    if found:
        _save_status(status)
    return found


def is_cancelled(job_id: str) -> bool:
    """Check whether a job has been marked cancelled. Used by ingestors to abort
    long-running extraction loops early once cancellation is requested."""
    for job in _load_status():
        if job["id"] == job_id:
            return job.get("status") == "cancelled"
    return False


def get_status() -> list:
    """Return current queue status for all jobs."""
    return _load_status()


_CLEARABLE_STATUSES = {"done", "cancelled"}


def clear_completed() -> None:
    """Remove done, cancelled, and errored jobs from the status file.
    This only affects the display queue — it never touches ChromaDB or the graph."""
    status = _load_status()
    _save_status(
        [
            j
            for j in status
            if j["status"] not in _CLEARABLE_STATUSES and not j["status"].startswith("error")
        ]
    )
