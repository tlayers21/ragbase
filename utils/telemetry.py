import threading

import requests

from config.logging import setup_logging
from config.runtime import DEVICE_ID, is_telemetry_enabled
from config.settings import TELEMETRY_URL

logger = setup_logging(__name__)

# Re-exported so callers (and scripts/metrics.py, which derives the /metrics URL from
# it) keep one import point for the sink address. The value itself is read in
# config/settings.py from the gitignored .env, so the address never reaches a tracked
# file. It is the project's only environment variable.
__all__ = ["TELEMETRY_URL", "send_telemetry"]


def send_telemetry(
    event_type: str, metadata: dict | None = None, device_id: str | None = None
) -> None:
    """Fire-and-forget anonymous telemetry event, never blocking or raising.

    Payloads carry the anonymous device_id only, never the user_id or any content.
    """
    if not TELEMETRY_URL or not is_telemetry_enabled():
        return

    payload = {
        "event_type": event_type,
        "device_id": device_id or DEVICE_ID,
        "metadata": metadata or {},
    }

    def _send():
        try:
            requests.post(TELEMETRY_URL, json=payload, timeout=2)
        except Exception:
            pass  # Sink unreachable - silently ignore

    threading.Thread(target=_send, daemon=True).start()
