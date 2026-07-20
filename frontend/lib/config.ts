// Single source of truth for the API base URL.
// Runtime overrides are read from localStorage by lib/api.ts — never
// reference localhost:8001 anywhere else in the codebase.
export const DEFAULT_API_URL = "http://localhost:8001";
export const DEFAULT_USER_ID = "test_user";
