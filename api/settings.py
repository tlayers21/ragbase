from fastapi import APIRouter
from pydantic import BaseModel

from config.logging import setup_logging
from config.runtime import (
    USER_ID,
    get_display_name,
    set_display_name,
    set_telemetry_enabled,
)

logger = setup_logging(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])


class TelemetryToggle(BaseModel):
    enabled: bool


class DisplayNameUpdate(BaseModel):
    display_name: str


@router.get("/user")
async def get_user():
    """Return the auto-generated local user ID and optional display name."""
    return {"user_id": USER_ID, "display_name": get_display_name()}


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
