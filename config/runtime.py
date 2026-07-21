"""Runtime identity and mutable settings.

USER_ID and DEVICE_ID are generated on first launch and persisted to
data/user_id.txt and data/device_id.txt. Mutable settings (telemetry opt-out,
display name) live in data/settings.json and override config/settings.py defaults.
"""

import json
import os
import secrets
import tempfile
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


def get_display_name() -> str | None:
    """Optional user-facing display name, or None if never set."""
    return _settings.get("display_name") or None


def set_display_name(display_name: str) -> None:
    """Update the display name and persist it."""
    _settings["display_name"] = display_name.strip()
    _save_settings()


load_settings()
