"""Runtime identity and mutable settings.

USER_ID and DEVICE_ID are generated on first launch and persisted to
data/user_id.txt and data/device_id.txt. Mutable settings (telemetry opt-out,
display name) live in data/settings.json and override config/settings.py defaults.

Also holds QUERY_IN_PROGRESS, the process-wide signal that a user is waiting on a
query right now — see the "Query priority" section below.
"""

import json
import os
import secrets
import tempfile
import threading
from pathlib import Path

from config.logging import setup_logging
from config.paths import DEVICE_ID_PATH, SETTINGS_JSON_PATH, USER_ID_PATH
from config.settings import TELEMETRY_ENABLED

logger = setup_logging(__name__)


# -- Identity ----------------------------------------------------------------
def _load_or_create_id(path: Path, prefix: str) -> str:
    """Read a persisted ID, generating and saving a new one on first launch."""
    if path.exists():
        value = path.read_text().strip()
        if value:
            return value
    value = f"{prefix}{secrets.token_hex(4)}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    logger.info(f"Generated new ID {value!r} at {path}")
    return value


USER_ID = _load_or_create_id(USER_ID_PATH, "usr_")
DEVICE_ID = _load_or_create_id(DEVICE_ID_PATH, "dev_")

# -- Mutable settings (data/settings.json) ------------------------------------
_settings: dict = {}


def load_settings() -> None:
    """Load data/settings.json overrides into memory. Missing file is fine."""
    global _settings
    if not SETTINGS_JSON_PATH.exists():
        _settings = {}
        return
    try:
        _settings = json.loads(SETTINGS_JSON_PATH.read_text())
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to read {SETTINGS_JSON_PATH}: {e}")
        _settings = {}


def _save_settings() -> None:
    """Persist settings atomically (temp file + os.replace)."""
    SETTINGS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=SETTINGS_JSON_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(_settings, f, indent=2)
        os.replace(tmp_path, SETTINGS_JSON_PATH)
    except OSError as e:
        logger.error(f"Failed to write {SETTINGS_JSON_PATH}: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def is_telemetry_enabled() -> bool:
    """Whether anonymous telemetry is enabled (settings.json overrides the default)."""
    return bool(_settings.get("telemetry_enabled", TELEMETRY_ENABLED))


def set_telemetry_enabled(enabled: bool) -> None:
    """Update the telemetry opt-out and persist it."""
    _settings["telemetry_enabled"] = enabled
    _save_settings()
    logger.info(f"Telemetry {'enabled' if enabled else 'disabled'}")


# -- Query priority ----------------------------------------------------------
# Everything in RAGbase shares one machine and one Ollama process, so a graph
# build (an LLM call per chunk, running for minutes) directly slows down any
# query the user runs while it is in flight. This flag lets the graph worker see
# that someone is actually waiting and back off between entity extractions
# instead of the query and the build fighting for the same CPU.
#
# It is a hint, not a lock: the build is only asked to pause briefly, never
# stopped, so a long build still makes progress while queries come and go.
#
# QUERY_IN_PROGRESS is the readable module-level flag; _active_queries is what
# actually maintains it, because concurrent queries would otherwise have the
# first one to finish clear the flag out from under the others.
QUERY_IN_PROGRESS = False
_active_queries = 0
_query_lock = threading.Lock()


def query_started() -> None:
    """Mark that a query is being served. Always pair with query_finished()."""
    global QUERY_IN_PROGRESS, _active_queries
    with _query_lock:
        _active_queries += 1
        QUERY_IN_PROGRESS = True


def query_finished() -> None:
    """Mark one query as complete (or failed). Clears the flag once none remain."""
    global QUERY_IN_PROGRESS, _active_queries
    with _query_lock:
        _active_queries = max(0, _active_queries - 1)
        QUERY_IN_PROGRESS = _active_queries > 0


def is_query_in_progress() -> bool:
    """Whether any query is currently being served."""
    return QUERY_IN_PROGRESS


# -- Startup warmup ----------------------------------------------------------
# Warmup pulls every model into memory before the first request (main.py
# lifespan). It is deliberately non-blocking so the server accepts connections
# immediately, but a query fired while it runs fights the warmup for the same
# GPU and either stalls for minutes or times out — which is exactly what a user
# does when the UI looks ready. This state is what makes that visible: GET
# /health reports it and the frontend gates its input on `ready`.
#
# Only the query-critical steps are registered, so the gate lifts as soon as a
# query can be served; ingestion-only models keep warming behind it.
_warmup_lock = threading.Lock()
_warmup_steps: tuple[str, ...] = ()
_warmup_completed: set[str] = set()
_warmup_current: str | None = None


def warmup_register(steps: tuple[str, ...]) -> None:
    """Declare the warmup steps that gate the UI. Call once, before they start."""
    global _warmup_steps
    with _warmup_lock:
        _warmup_steps = tuple(steps)
        _warmup_completed.clear()


def warmup_started(step: str) -> None:
    """Mark `step` as the one currently loading — the label shown while waiting."""
    global _warmup_current
    with _warmup_lock:
        _warmup_current = step


def warmup_finished(step: str) -> None:
    """
    Mark `step` as no longer pending.

    Called for failures too: a model that won't load must not hold the UI closed
    forever, and the first real request will surface the error properly.
    """
    global _warmup_current
    with _warmup_lock:
        _warmup_completed.add(step)
        if _warmup_current == step:
            _warmup_current = None


def get_warmup_status() -> dict:
    """Progress snapshot for GET /health: ready, current step, and counts."""
    with _warmup_lock:
        pending = [s for s in _warmup_steps if s not in _warmup_completed]
        return {
            "ready": not pending,
            "current": _warmup_current,
            "completed": len(_warmup_steps) - len(pending),
            "total": len(_warmup_steps),
        }


def get_display_name() -> str | None:
    """Optional user-facing display name, or None if never set."""
    return _settings.get("display_name") or None


def set_display_name(display_name: str) -> None:
    """Update the display name and persist it."""
    _settings["display_name"] = display_name.strip()
    _save_settings()


load_settings()
