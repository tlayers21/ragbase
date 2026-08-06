from fastapi import APIRouter

from config.logging import setup_logging
from config.paths import DATA_DIR

logger = setup_logging(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])

RESET_FLAG = DATA_DIR / "reset_sessions_flag"


@router.get("/should_reset")
def should_reset():
    """
    Returns {reset: true} once after reset_all.sh creates the flag file, then
    deletes the flag so subsequent calls return {reset: false}.
    The frontend calls this on startup to know whether to wipe localStorage chat history.
    """
    if RESET_FLAG.exists():
        try:
            RESET_FLAG.unlink()
        except OSError as e:
            logger.warning(f"Failed to remove reset flag: {e}")
        logger.info("Session reset flag consumed — frontend will clear chat history")
        return {"reset": True}
    return {"reset": False}
