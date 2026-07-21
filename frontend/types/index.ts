// ── API response shapes ──────────────────────────────────────────────────────

export interface SourceSummary {
  source: string;
  chunk_count: number;
  flagged_count: number;
  contradiction_count: number;
}

export interface IngestionJob {
  id: string;
  filename: string;
  source: string;
  suffix: string;
  status: string;
  tmp_path?: string;
  estimated_seconds?: number;
}

export interface IngestionStatus {
  jobs: IngestionJob[];
}

// ── App-local types ──────────────────────────────────────────────────────────

export type MessageRole = "user" | "assistant" | "system";

export interface CitedChunk {
  source: string;
  score: number;
  text: string;
}

export type QueryMode = "rag" | "direct";

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  sources?: string[];
  scores?: number[];
  chunks?: CitedChunk[];
  timestamp: number;
  /** Which endpoint served this response — set once streaming completes. */
  mode?: QueryMode;
  /** Retrieval stage while streaming ("retrieving_sources" | "reranking" | "generating"). */
  stage?: string;
  /** Generation latency in ms (first token → [DONE]). */
  latencyMs?: number;
  /** True once onDone fires — guards sources section from rendering during streaming. */
  isComplete?: boolean;
  /** "summary" for auto-compacted conversation summary messages. */
  type?: "summary";
}

export interface ChatSession {
  id: string;
  title: string;
  messages: Message[];
  createdAt: number;
  updatedAt: number;
  pinned?: boolean;
}
