// The only place localhost:8001 appears - lib/api.ts applies localStorage overrides
export const DEFAULT_API_URL = "http://localhost:8001";

// Model loads take seconds, so polling faster only adds requests to a busy backend
export const HEALTH_POLL_INTERVAL_MS = 1000;

// Switches the gate's copy only, never unblocks it - a cold start.sh is slow
export const HEALTH_STALL_AFTER_MS = 60_000;

// RERANKER_MIN_SCORE on the UI's relevance scale - the slider's default and marker
export const DEFAULT_RELEVANCE_PERCENT = 44;

// Matched pair with NUM_CTX_STANDARD - change one and you must change the other
export const ANSWER_CONTEXT_TOKENS = 24576;

// Held back for the current turn's retrieved chunks, which the client cannot see
export const RETRIEVAL_RESERVE_TOKENS = 4096;

// Held back for the system prompt and the answer itself, which share the window
export const ANSWER_RESERVE_TOKENS = 4096;

// Matched pair with config/settings.py HISTORY_TOKEN_BUDGET - change both or neither
export const HISTORY_TOKEN_BUDGET =
  ANSWER_CONTEXT_TOKENS - RETRIEVAL_RESERVE_TOKENS - ANSWER_RESERVE_TOKENS;

// Fraction of HISTORY_TOKEN_BUDGET at which compaction fires and the usage bar turns red
export const COMPACT_THRESHOLD = 0.9;

// Filters the OS file picker only - the backend is still the authority
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
