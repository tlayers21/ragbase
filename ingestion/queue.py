import json
import os
import queue
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from config.logging import setup_logging
from config.paths import QUEUE_STATUS_PATH
from config.settings import (
    QUEUE_TERMINAL_ROW_TTL_SECONDS,
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

# "error: <msg>" is terminal too, matched by prefix because it carries the message
_CLEARABLE_STATUSES = {"done", "cancelled"}


def _is_terminal(status: str) -> bool:
    """Whether a status means the worker has finished with the job, one way or another."""
    return status in _CLEARABLE_STATUSES or status.startswith("error")


# -- Status file helpers ---------------------------------------------------
# The worker and API threads read-modify-write one shared JSON file concurrently
_status_lock = threading.RLock()

# The job the worker is executing right now - a job whose record vanishes never stops
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


def _mutate_job(job_id: str, mutate: Callable[[dict], None]) -> None:
    """Apply `mutate` to one job under the lock and persist, or do nothing if it is gone.

    Skipping the write on a miss matters: a job whose row was already swept would
    otherwise rewrite the whole file to change nothing.
    """
    with _status_lock:
        status = _load_status()
        for job in status:
            if job["id"] == job_id:
                mutate(job)
                _save_status(status)
                return


def _update_job(job_id: str, new_status: str) -> None:
    def apply(job: dict) -> None:
        job["status"] = new_status
        # Counts belong to one phase, so a phase change invalidates them
        job.pop("progress", None)
        # Stamped so get_status() can expire it - nothing else removes a finished row
        if _is_terminal(new_status):
            job["finished_at"] = time.time()
        else:
            job.pop("finished_at", None)

    _mutate_job(job_id, apply)


def update_job_estimate(job_id: str, estimated_seconds: int) -> None:
    """Update the time estimate for an active job."""
    _mutate_job(job_id, lambda job: job.__setitem__("estimated_seconds", estimated_seconds))


def update_job_progress(job_id: str, current: int, total: int, unit: str = "page") -> None:
    """Record "unit `current` of `total`" for an active job, for the UI's progress bar.

    Only phases with a countable loop set it; _update_job clears it on any status change.
    """
    _mutate_job(
        job_id,
        lambda job: job.__setitem__("progress", {"current": current, "total": total, "unit": unit}),
    )


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


def _duplicate_job_id(source: str, user_id: str) -> str | None:
    """The id of an already-active job for this source, or None if it is free to enqueue.

    Taken under the lock so the check cannot race the _add_job it is guarding.
    """
    with _status_lock:
        existing = _find_active_job(source, user_id)
        if not existing:
            return None
        logger.warning(
            f"Skipping duplicate enqueue for source '{source}' and user '{user_id}' "
            f"because job '{existing['id']}' is already active ({existing.get('status')})"
        )
        return existing["id"]


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
    """Background thread that runs each job end to end - extraction through the
    knowledge graph - one job at a time."""
    while True:
        job = _queue.get()
        if job is None:
            break

        job_id = job["id"]
        source = job["source"]
        user_id = job["user_id"]
        suffix = job["suffix"]
        tmp_path = job["tmp_path"]

        # Before the first status write, or that write clobbers "cancelled" back to "ingesting"
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
            # Lazy so per-format deps load only when a job of that type is processed
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
            # Held until the graph build ends too, so crash recovery can re-run from tmp_path
            if suffix != ".url" and not job.get("is_string"):
                try:
                    os.remove(tmp_path)
                except OSError as e:
                    logger.warning(f"Could not remove temp file for '{source}': {e}")

            # Hand the GPU back, on this thread, where no user is waiting on it
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
    """Save a file to a temp location, add it to the queue, and return the job ID.

    `describe_images` only affects PDFs, turning on the opt-in figure-description pass.
    """
    suffix = Path(filename).suffix.lower()
    duplicate = _duplicate_job_id(source, user_id)
    if duplicate:
        return duplicate

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
        # anydoc conversion is near-instant; the summary LLM call dominates
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
    duplicate = _duplicate_job_id(source, user_id)
    if duplicate:
        return duplicate

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
    duplicate = _duplicate_job_id(source, user_id)
    if duplicate:
        return duplicate

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
                job["finished_at"] = time.time()
                # Counts belong to the interrupted phase and would read as still working
                job.pop("progress", None)
                found = True
                break
        if found:
            _save_status(status)
    return found


def find_active_job(source: str, user_id: str) -> dict | None:
    """Return the job holding this source, or None, on the same terms as active_sources.

    A cancelled job the worker still owns counts, so guards and retrieval cannot
    disagree about whether a source being torn down is still in flight.
    """
    with _status_lock:
        job = _find_active_job(source, user_id)
        if job:
            return job
        running = _current_job_id
        for candidate in _load_status():
            if (
                candidate.get("source") == source
                and candidate.get("user_id") == user_id
                and candidate.get("status") == "cancelled"
                and candidate.get("id") == running
            ):
                return candidate
        return None


def active_sources(user_id: str) -> set[str]:
    """Source names that still have a job in flight for this user.

    A job the worker still owns counts as in flight even once it reads "cancelled",
    because its chunks are still in ChromaDB for the length of the teardown.
    """
    with _status_lock:
        running = _current_job_id
        return {
            job["source"]
            for job in _load_status()
            if job.get("user_id") == user_id
            and job.get("source")
            and (
                job.get("status") in _ACTIVE_STATUSES
                or (job.get("status") == "cancelled" and job["id"] == running)
            )
        }


def is_cancelled(job_id: str) -> bool:
    """Check whether a job has been marked cancelled, so ingestors can abort early.

    A missing record counts as cancelled; returning False let a build run to completion
    after its record was cleared.
    """
    for job in _load_status():
        if job["id"] == job_id:
            return job.get("status") == "cancelled"
    logger.warning(f"Job '{job_id}' has no status record - treating as cancelled")
    return True


def get_status() -> list:
    """Return current queue status for all jobs, expiring long-finished rows first.

    The sweep lives on the read path because it is the only code guaranteed to run once
    a job ends; rows with no finished_at are treated as long expired.
    """
    cutoff = time.time() - QUEUE_TERMINAL_ROW_TTL_SECONDS
    with _status_lock:
        status = _load_status()
        # The running job is kept regardless - it polls its own record to learn to stop
        running = _current_job_id
        kept = [
            job
            for job in status
            if job["id"] == running
            or not _is_terminal(job.get("status", ""))
            or job.get("finished_at", 0) > cutoff
        ]
        if len(kept) != len(status):
            logger.info(f"Expired {len(status) - len(kept)} finished job row(s) from the queue")
            _save_status(kept)
        return kept


def clear_completed() -> None:
    """Remove done, cancelled, and errored jobs from the display queue only.

    The job the worker currently owns is kept even when its status is clearable, because
    a cooperatively cancelled job still polls its own record.
    """
    with _status_lock:
        running = _current_job_id
        _save_status(
            [
                j
                for j in _load_status()
                if j["id"] == running or not _is_terminal(j.get("status", ""))
            ]
        )
