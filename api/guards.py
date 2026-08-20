import asyncio

from fastapi import HTTPException

from config.runtime import USER_ID
from ingestion.queue import find_active_job


async def require_finished(source: str) -> None:
    """Raise 409 if `source` still has a job in flight.

    409 rather than 404 because the source exists and is merely unfinished; the queue
    status file is the authority, since the data lands in ChromaDB well before "done".
    """
    job = await asyncio.to_thread(find_active_job, source, USER_ID)
    if job:
        raise HTTPException(
            status_code=409,
            detail=f"Source '{source}' is still being ingested ({job.get('status')})",
        )
