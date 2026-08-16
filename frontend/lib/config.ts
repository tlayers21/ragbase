// Single source of truth for the API base URL.
// Runtime overrides are read from localStorage by lib/api.ts — never
// reference localhost:8001 anywhere else in the codebase.
export const DEFAULT_API_URL = "http://localhost:8001";

// How often the warmup gate re-checks GET /health while models load. Model loads
// take seconds, so polling faster only adds requests the backend answers while
// it is already busy.
export const HEALTH_POLL_INTERVAL_MS = 1000;

// How long the warmup gate waits for a *first* successful /health response before
// switching to troubleshooting copy. This changes wording only — it never unblocks
// the UI, because a backend that can't be reached can't answer a query either.
// Generous on purpose: a cold `start.sh` can spend a while on the frontend build
// before the browser opens, and the backend may still be binding its port.
export const HEALTH_STALL_AFTER_MS = 60_000;

// Mirrors SUPPORTED_EXTENSIONS in config/settings.py. The backend is still the
// authority — this only filters the OS file picker, and drag-and-drop bypasses
// it entirely, so an unsupported file is rejected server-side either way.
export const ACCEPTED_INGEST_TYPES = [
  ".pdf",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".tiff",
  ".mp4",
  ".mov",
  ".avi",
  ".mkv",
  ".webm",
  ".txt",
  ".md",
  ".doc",
  ".docx",
  ".docm",
  ".ppt",
  ".pptx",
  ".pptm",
  ".pps",
  ".ppsx",
  ".ppsm",
  ".pot",
  ".xls",
  ".xlsx",
  ".xlsm",
  ".xlsb",
  ".odt",
  ".ods",
  ".odp",
  ".rtf",
  ".epub",
  ".csv",
].join(",");
