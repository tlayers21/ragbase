import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from config.logging import setup_logging
from config.runtime import (
    USER_ID,
    get_display_name,
    get_reranker_min_score,
    set_display_name,
    set_reranker_min_score,
    set_telemetry_enabled,
)
from config.settings import RELEVANCE_SCALE_MAX, RELEVANCE_SCALE_MIN
from utils.cache import clear_cache

logger = setup_logging(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])


class TelemetryToggle(BaseModel):
    enabled: bool


class DisplayNameUpdate(BaseModel):
    display_name: str


class RerankerThreshold(BaseModel):
    """The absolute relevance floor, in raw BGE-reranker logits (not a percentage).

    The frontend renders it as a percentage but converts before sending, so scores
    stay in one unit everywhere on this side.
    """

    min_score: float


@router.get("/user")
async def get_user():
    """Return the auto-generated local user ID, display name, and retrieval floor."""
    return {
        "user_id": USER_ID,
        "display_name": get_display_name(),
        "reranker_min_score": get_reranker_min_score(),
    }


@router.post("/telemetry")
async def update_telemetry(req: TelemetryToggle):
    """Enable or disable anonymous telemetry. Persisted to data/settings.json."""
    set_telemetry_enabled(req.enabled)
    return {"status": "ok", "enabled": req.enabled}


@router.post("/display_name")
async def update_display_name(req: DisplayNameUpdate):
    """Set the optional display name. Persisted to data/settings.json."""
    set_display_name(req.display_name)
    return {"status": "ok", "display_name": get_display_name()}


@router.post("/reranker_threshold")
async def update_reranker_threshold(req: RerankerThreshold):
    """
    Set the relevance floor for retrieved chunks. Persisted to data/settings.json.

    Applies to the next query with no restart - `rerank_candidates()` reads the
    getter per call rather than an import-time constant.

    The semantic cache is cleared as part of this. A cache hit returns stored
    chunks and skips reranking entirely (24h TTL), so without this the new
    threshold would silently do nothing to any recently-asked question - which
    reads as the setting being broken.
    """
    score = max(RELEVANCE_SCALE_MIN, min(RELEVANCE_SCALE_MAX, req.min_score))
    set_reranker_min_score(score)
    cleared = await asyncio.to_thread(clear_cache, USER_ID)
    logger.info(f"Cleared {cleared} cached responses after threshold change")
    return {"status": "ok", "min_score": score, "cache_cleared": cleared}
