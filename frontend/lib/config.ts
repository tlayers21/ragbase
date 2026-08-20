// Single source of truth for the API base URL.
// Runtime overrides are read from localStorage by lib/api.ts - never
// reference localhost:8001 anywhere else in the codebase.
export const DEFAULT_API_URL = "http://localhost:8001";

// How often the warmup gate re-checks GET /health while models load. Model loads
// take seconds, so polling faster only adds requests the backend answers while
// it is already busy.
export const HEALTH_POLL_INTERVAL_MS = 1000;

// How long the warmup gate waits for a *first* successful /health response before
// switching to troubleshooting copy. This changes wording only - it never unblocks
// the UI, because a backend that can't be reached can't answer a query either.
// Generous on purpose: a cold `start.sh` can spend a while on the frontend build
// before the browser opens, and the backend may still be binding its port.
export const HEALTH_STALL_AFTER_MS = 60_000;

// The shipped RERANKER_MIN_SCORE (-2.0) expressed on the relevance scale the UI
// shows. Used as the settings slider's starting value before the backend answers,
// and as the "recommended" marker beside it. Mirrors config/settings.py.
export const DEFAULT_RELEVANCE_PERCENT = 44;

// The context window the answer model is actually loaded with. **Mirrors
// config/settings.py::NUM_CTX_STANDARD** - a matched pair, like
// relevancePercent and RELEVANCE_SCALE_*. Change one and you must change the other.
//
// This used to read 40960, qwen3's architectural maximum, which the backend never
// requested: with no num_ctx in the request Ollama applied a 4096 default. So the
// compaction trigger was calibrated against a ceiling ten times the real one and
// effectively never fired in time.
export const ANSWER_CONTEXT_TOKENS = 24576;

// Held back from history for the parts of the prompt the client can't see: the
// current turn's retrieved chunks (MAX_FINAL_RESULTS = 5, ~770 tokens each) plus
// the system prompt.
export const RETRIEVAL_RESERVE_TOKENS = 4096;

// What conversation history may actually occupy. Both the compaction trigger and
// the sidebar's usage bar measure against this, so the bar filling up and
// compaction firing are the same event rather than two unrelated numbers.
export const HISTORY_TOKEN_BUDGET = ANSWER_CONTEXT_TOKENS - RETRIEVAL_RESERVE_TOKENS;

// Mirrors SUPPORTED_EXTENSIONS in config/settings.py. The backend is still the
// authority - this only filters the OS file picker, and drag-and-drop bypasses
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
