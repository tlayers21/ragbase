from fastapi import APIRouter

from config.logging import setup_logging
from config.paths import DATA_DIR

logger = setup_logging(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])

RESET_FLAG = DATA_DIR / "reset_sessions_flag"


@router.get("/should_reset")
def should_reset():
    """Return {reset_at} - the mtime of the most recent reset_all.sh run, or null.

    Deliberately not one-shot: clients compare it to the last value they acted on, so a
    reset reaches every tab rather than only whichever asked first.
    """
    if not RESET_FLAG.exists():
        return {"reset_at": None}
    try:
        return {"reset_at": RESET_FLAG.stat().st_mtime}
    except OSError as e:
        # An unreadable flag means "no reset" - failing here would block chat history
        logger.warning(f"Failed to stat reset flag: {e}")
        return {"reset_at": None}
