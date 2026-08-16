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
    SUPPORTED_OFFICE_EXTENSIONS,
    SUPPORTED_PDF_EXTENSIONS,
    SUPPORTED_TEXT_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
)
from utils.ollama_client import restore_query_models

logger = setup_logging(__name__)


_queue = queue.Queue()
_worker_thread = None

_ACTIVE_STATUSES = {"queued", "ingesting", "building_graph"}


# -- Status file helpers ---------------------------------------------------
# Every status update is a read-modify-write of one shared JSON file, performed by
# the ingestion worker and API request threads concurrently. Two problems follow,
# and this lock is what prevents both:
#   1. Lost updates — two threads load the same list, each edits one job, and the
#      second write discards the first thread's edit.
#   2. A crash — every writer used to build the same "queue_status.json.tmp" path,
#      so whichever called os.replace() second hit FileNotFoundError and blew up
#      its caller, leaving the status file empty and the UI showing no jobs at all.
#      That was found when ingestion and graph builds ran on two separate workers;
#      merging them into one job removed that particular race, but the API threads
#      (cancel, clear_completed) still write here while the worker does.
# The unique temp name below is belt-and-braces for anything holding a stale
# reference to these helpers from outside the lock.
_status_lock = threading.RLock()

# The job the worker is executing right now, or None between jobs. clear_completed()
# reads it so a "cancelled" record can't be deleted out from under a job that is
# still running - doing so left the worker with no record to check, and a job whose
# record has vanished has nothing to stop it.
_current_job_id: str | None = None


def _set_current_job(job_id: str | None) -> None:
    """Record which job the worker owns, for clear_completed()'s benefit."""
    global _current_job_id
    with _status_lock:
        _current_job_id = job_id


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
    fd, tmp = tempfile.mkstemp(dir=QUEUE_STATUS_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(status, f)
        os.replace(tmp, QUEUE_STATUS_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _update_job(job_id: str, new_status: str) -> None:
    with _status_lock:
        status = _load_status()
        for job in status:
            if job["id"] == job_id:
                job["status"] = new_status
                # Progress counts what the *current* phase is working through, so a
                # phase change invalidates them. Without this, "Page 4 of 4" from
                # extraction stays on screen through the whole graph build and past
                # "done", reading as a stalled job.
                job.pop("progress", None)
                break
        _save_status(status)


def update_job_estimate(job_id: str, estimated_seconds: int) -> None:
    """Update the time estimate for an active job."""
    with _status_lock:
        status = _load_status()
        for job in status:
            if job["id"] == job_id:
                job["estimated_seconds"] = estimated_seconds
                break
        _save_status(status)


def update_job_progress(job_id: str, current: int, total: int, unit: str = "page") -> None:
    """
    Record "unit `current` of `total`" for an active job, for the UI's progress bar.

    Optional by design: only phases with a countable loop set it (PDF pages on the
    VLM and Docling paths, chunks during the graph build). Everything else leaves it
    absent and the frontend falls back to its time-based estimate. Cleared by
    _update_job on any status change.
    """
    with _status_lock:
        status = _load_status()
        for job in status:
            if job["id"] == job_id:
                job["progress"] = {"current": current, "total": total, "unit": unit}
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
    with _status_lock:
        status = _load_status()
        job_record = {**job, "status": "queued"}
        status.append(job_record)
        _save_status(status)


def _requeue_recovered_jobs() -> int:
    """Recover queued jobs from disk after a restart."""
    recovered = 0

    with _status_lock:
        status = _load_status()
        changed = False

        for job in status:
            job_status = job.get("status")
            if job_status in _ACTIVE_STATUSES:
                if job_status != "queued":
                    job["status"] = "queued"
                    changed = True

                if not job.get("source") or not job.get("user_id") or "tmp_path" not in job:
                    logger.warning(
                        f"Skipping unrecoverable queued job '{job.get('id')}' after restart"
                    )
                    continue

                _queue.put(job)
                recovered += 1

        if changed:
            _save_status(status)

    return recovered


# -- Worker ----------------------------------------------------------------
def _worker():
    """Background thread that runs each job end to end — extraction through the
    knowledge graph — one job at a time."""
    while True:
        job = _queue.get()
        if job is None:
            break

        job_id = job["id"]
        source = job["source"]
        user_id = job["user_id"]
        suffix = job["suffix"]
        tmp_path = job["tmp_path"]

        # Cancellation has to be honoured *before* the first status write, or that
        # write clobbers "cancelled" back to "ingesting" and the job runs anyway.
        # A job can now sit queued for the length of the graph build ahead of it,
        # so cancelling something that never started is the common case, not a
        # narrow race.
        if is_cancelled(job_id):
            logger.info(f"Skipping cancelled job '{source}' before it started")
            if suffix != ".url" and not job.get("is_string"):
                try:
                    os.remove(tmp_path)
                except OSError as e:
                    logger.warning(f"Could not remove temp file for cancelled '{source}': {e}")
            _queue.task_done()
            continue

        _set_current_job(job_id)
        _update_job(job_id, "ingesting")
        logger.info(f"Ingesting job '{source}' ({suffix}) for user '{user_id}'")

        try:
            # Ingestors are imported lazily here (not at module top) so their
            # heavy per-format dependencies (docling, paddleocr, whisper,
            # yt-dlp) only load when a job of that type is actually processed.
            if suffix in SUPPORTED_PDF_EXTENSIONS:
                from ingestion.pdf import PdfIngestor

                ingestor = PdfIngestor(
                    user_id, job_id=job_id, describe_images=job.get("describe_images", False)
                )
                ingestor.ingest(tmp_path, source)

            elif suffix in SUPPORTED_OFFICE_EXTENSIONS:
                from ingestion.office import OfficeIngestor

                ingestor = OfficeIngestor(user_id, job_id=job_id)
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
            # Held until the graph build finishes too, not just extraction. That
            # costs nothing in peak disk (every queued job already has its temp
            # copy on disk from enqueue time) and it is what makes crash recovery
            # work: _requeue_recovered_jobs re-runs the whole job from tmp_path,
            # which used to be deleted the moment extraction ended.
            if suffix != ".url" and not job.get("is_string"):
                try:
                    os.remove(tmp_path)
                except OSError as e:
                    logger.warning(f"Could not remove temp file for '{source}': {e}")

            # The job is completely over — extraction and graph build both — so
            # hand the GPU back to queries. An ingest that touched the vision
            # model leaves it resident holding 7.3GB, with the answer model
            # evicted to make room, so without this the next question pays a
            # cold load. Runs on this worker thread, where no user is waiting.
            # See utils/ollama_client.py::restore_query_models for the measured
            # eviction trace and why serializing the calls would not have helped.
            try:
                restore_query_models()
            except Exception as e:
                logger.warning(f"Could not restore query models after '{source}': {e}")

            _set_current_job(None)
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
    describe_images: bool = False,
) -> str:
    """
    Add a file to the ingestion queue. Saves file to a temp location
    and returns the job ID. The worker processes it in the background.

    `describe_images` only affects PDFs — it turns on the opt-in Docling + VLM
    figure-description pass (see PdfIngestor).
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

    file_size_mb = len(file_bytes) / 1_048_576
    if suffix in SUPPORTED_PDF_EXTENSIONS:
        estimated_seconds = max(5, int(file_size_mb * 1.5))
    elif suffix in SUPPORTED_IMAGE_EXTENSIONS:
        estimated_seconds = 15
    elif suffix in SUPPORTED_VIDEO_EXTENSIONS:
        estimated_seconds = max(5, int(file_size_mb * 1.0))
    elif suffix in SUPPORTED_TEXT_EXTENSIONS:
        estimated_seconds = 3
    elif suffix in SUPPORTED_OFFICE_EXTENSIONS:
        # anydoc conversion is near-instant; the summary LLM call dominates.
        estimated_seconds = 10
    else:
        estimated_seconds = 30

    job = {
        "id": job_id,
        "filename": filename,
        "source": source,
        "user_id": user_id,
        "suffix": suffix,
        "tmp_path": tmp_path,
        "estimated_seconds": estimated_seconds,
        "describe_images": describe_images,
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
        "estimated_seconds": 30,
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
        "estimated_seconds": 3,
    }

    _add_job(job)
    _queue.put(job)

    logger.info(f"Enqueued text '{source}' for user '{user_id}'")
    return job_id


def cancel_job(job_id: str) -> bool:
    """Mark an active job as cancelled. Returns True if the job was found and cancellable."""
    with _status_lock:
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


def find_active_job(source: str, user_id: str) -> dict | None:
    """
    Return the active job for a source, or None.

    Public counterpart to `_find_active_job` for callers outside this module —
    `api/documents.py` uses it to stop an in-flight ingestion or graph build
    before deleting the source out from under it.
    """
    with _status_lock:
        return _find_active_job(source, user_id)


def active_sources(user_id: str) -> set[str]:
    """
    Source names that still have a job in flight for this user.

    The queue status file is the authority on "is this source finished". A job
    stores its chunks in ChromaDB minutes before the graph build that completes
    it, so retrieval has to exclude these explicitly — otherwise a document the
    UI is still showing as in-progress can answer a question with a partial
    graph behind it. Read once per query in `search_candidates()`.
    """
    with _status_lock:
        return {
            job["source"]
            for job in _load_status()
            if job.get("user_id") == user_id
            and job.get("source")
            and job.get("status") in _ACTIVE_STATUSES
        }


def is_cancelled(job_id: str) -> bool:
    """Check whether a job has been marked cancelled. Used by ingestors to abort
    long-running extraction loops early once cancellation is requested.

    A missing record counts as cancelled. It used to return False, which meant
    clear_completed() deleting a cancelled-but-still-running job's record turned
    every later poll into "keep going": the build ran to completion, the cleanup
    never fired, and the source became queryable with a half-written graph.
    """
    for job in _load_status():
        if job["id"] == job_id:
            return job.get("status") == "cancelled"
    logger.warning(f"Job '{job_id}' has no status record - treating as cancelled")
    return True


def get_status() -> list:
    """Return current queue status for all jobs."""
    return _load_status()


_CLEARABLE_STATUSES = {"done", "cancelled"}


def clear_completed() -> None:
    """Remove done, cancelled, and errored jobs from the status file.

    This only affects the display queue - it never touches ChromaDB or the graph.

    The job the worker currently owns is kept even when its status is clearable.
    Cancellation is cooperative, so a job sits at "cancelled" while it is still
    running; deleting that record left the worker unable to see it had been
    cancelled, and the source went on to finish and become queryable.
    """
    with _status_lock:
        running = _current_job_id
        _save_status(
            [
                j
                for j in _load_status()
                if j["id"] == running
                or (j["status"] not in _CLEARABLE_STATUSES and not j["status"].startswith("error"))
            ]
        )
