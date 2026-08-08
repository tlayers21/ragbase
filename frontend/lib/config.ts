// Single source of truth for the API base URL.
// Runtime overrides are read from localStorage by lib/api.ts — never
// reference localhost:8001 anywhere else in the codebase.
export const DEFAULT_API_URL = "http://localhost:8001";

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
