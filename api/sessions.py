from fastapi import APIRouter

from config.logging import setup_logging
from config.paths import DATA_DIR

logger = setup_logging(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])

RESET_FLAG = DATA_DIR / "reset_sessions_flag"


@router.get("/should_reset")
def should_reset():
    """
    Returns {reset_at: <mtime>} - the time of the most recent reset_all.sh run, or
    null if the app has never been reset.

    Chat sessions live in the browser's localStorage and never on the backend, so
    this endpoint is the only route by which a backend reset can reach them. The
    frontend remembers the last value it acted on and clears its history whenever a
    newer one arrives.

    Deliberately *not* one-shot. This used to delete the flag on first read, which
    made a reset a race: whichever browser or tab asked first consumed it and every
    other one kept its history, and a read that failed because the backend wasn't up
    yet consumed it just as effectively. reset_all.sh touches the flag on each run,
    so the mtime moves forward and every client converges on its own schedule.
    """
    if not RESET_FLAG.exists():
        return {"reset_at": None}
    try:
        return {"reset_at": RESET_FLAG.stat().st_mtime}
    except OSError as e:
        # Treat an unreadable flag as "no reset" rather than failing the request -
        # the frontend would otherwise be unable to load chat history at all.
        logger.warning(f"Failed to stat reset flag: {e}")
        return {"reset_at": None}
