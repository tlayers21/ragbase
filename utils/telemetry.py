import threading

import requests

from config.logging import setup_logging

logger = setup_logging(__name__)

TELEMETRY_URL = "http://100.80.105.44:9000/telemetry"


def send_telemetry(event_type: str, user_id: str = "unknown", metadata: dict = None) -> None:
    """Fire-and-forget telemetry event to Pi. Never blocks or raises."""

    def _send():
        try:
            requests.post(
                TELEMETRY_URL,
                json={"event_type": event_type, "user_id": user_id, "metadata": metadata or {}},
                timeout=2,
            )
        except Exception:
            pass  # Pi unreachable — silently ignore

    threading.Thread(target=_send, daemon=True).start()
