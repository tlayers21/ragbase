import asyncio

from fastapi import HTTPException

from config.logging import setup_logging
from config.runtime import USER_ID
from ingestion.queue import find_active_job

logger = setup_logging(__name__)


async def require_finished(source: str) -> None:
    """409 if `source` still has a job in flight.

    409 rather than 404 on purpose: the source exists, it is just not finished,
    and the two need different handling on the client. The queue status file is
    the authority on "finished" - chunks and the summary are physically in
    ChromaDB, and the original file on disk, minutes before the graph build that
    completes the job, so the presence of data proves nothing.

    Every endpoint that reads a whole source needs this, which is why it lives
    here: rendering it (documents), serving its file (sources) and explaining it
    (query) each independently returned partial data at some point.
    """
    job = await asyncio.to_thread(find_active_job, source, USER_ID)
    if job:
        raise HTTPException(
            status_code=409,
            detail=f"Source '{source}' is still being ingested ({job.get('status')})",
        )
