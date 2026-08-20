import threading

import requests

from config.logging import setup_logging
from config.runtime import DEVICE_ID, is_telemetry_enabled

logger = setup_logging(__name__)

TELEMETRY_URL = "http://100.80.105.44:9000/telemetry"


def send_telemetry(
    event_type: str, metadata: dict | None = None, device_id: str | None = None
) -> None:
    """Fire-and-forget anonymous telemetry event to the Pi, never blocking or raising.

    Payloads carry the anonymous device_id only, never the user_id or any content.
    """
    if not is_telemetry_enabled():
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
            pass  # Pi unreachable - silently ignore

    threading.Thread(target=_send, daemon=True).start()
