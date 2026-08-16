// -- API response shapes ------------------------------------------------------

export interface SourceSummary {
  source: string;
  chunk_count: number;
  flagged_count: number;
  contradiction_count: number;
  /** Opening characters of the source's first chunk. Used to preview sources with
   * no previewable original on disk - YouTube transcripts and office formats. */
  preview: string;
  /** Extension of the stored original (".pdf", ".png", ...), "" if no file is stored.
   * Needed to address the file on the Next.js static mount - the source name is a
   * slug and carries no extension. */
  file_ext: string;
}

/** The full status lifecycle of an ingestion job, in order. One job runs
 * extraction *and* its knowledge graph build, so `done` means both are finished.
 * A failure is the literal string `error: <detail>` instead, which is why
 * `IngestionJob.status` stays a plain string - consumers prefix-match on it. */
export type IngestionJobStatus =
  | "queued"
  | "ingesting"
  | "building_graph"
  | "done"
  | "cancelled";

export interface IngestionJob {
  id: string;
  filename: string;
  source: string;
  suffix: string;
  /** An `IngestionJobStatus`, or `error: <detail>`. */
  status: string;
  tmp_path?: string;
  /** Seconds the current phase is expected to take. Rewritten when the graph
   * phase starts, so it always describes the phase the job is in now. */
  estimated_seconds?: number;
  /** Real countable progress through the current phase, when the phase has a
   * countable loop: PDF pages on the VLM and Docling paths, chunks during the
   * graph build. Absent everywhere else - notably the anydoc typed-PDF path,
   * which is one opaque subprocess - so consumers must fall back to
   * `estimated_seconds`. Cleared by the backend on every status change. */
  progress?: { current: number; total: number; unit?: string };
}

export interface IngestionStatus {
  jobs: IngestionJob[];
}

/** GET /health - liveness plus startup warmup progress (main.py lifespan). */
export interface HealthStatus {
  status: string;
  /** False while the models a query needs are still loading. The UI stays gated until true. */
  ready: boolean;
  /** Warmup step currently loading ("embed" | "answer" | "reranker"), null between steps. */
  current: string | null;
  completed: number;
  total: number;
}

// -- App-local types ----------------------------------------------------------

export type MessageRole = "user" | "assistant" | "system";

export interface CitedChunk {
  source: string;
  score: number;
  text: string;
}

export type QueryMode = "rag" | "direct";

export type AttachmentType = "image" | "pdf" | "text";

/** Attachment metadata stored on a sent user message. `description` is the VLM
 * output (image) or extracted text (pdf/text) - re-sent in history on every
 * subsequent turn so follow-up questions retain the attachment's context. */
export interface MessageAttachment {
  type: AttachmentType;
  name: string;
  description: string;
  /** Client-side object URL for image thumbnails only - not persisted across reloads. */
  previewUrl?: string;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  sources?: string[];
  scores?: number[];
  chunks?: CitedChunk[];
  attachments?: MessageAttachment[];
  timestamp: number;
  /** Which endpoint served this response - set once streaming completes. */
  mode?: QueryMode;
  /** Retrieval stage while streaming ("retrieving_sources" | "reranking" | "generating"). */
  stage?: string;
  /** End-to-end latency in ms: from the moment the API received the question to
   * the moment this answer's final token was painted. Built from the server's own
   * elapsed time (the [TIMING] frame) plus the browser's time from that frame to
   * the post-commit paint, so no clock is ever compared across the two.
   *
   * It used to measure first-token -> [DONE] entirely in the browser, which
   * excluded retrieval, reranking and every millisecond before the first token -
   * i.e. most of what makes a query slow. */
  latencyMs?: number;
  /** True once onDone fires - guards sources section from rendering during streaming. */
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

// -- Chat input attachments (pre-send, client-only) ----------------------------

/** An attachment staged in ChatInput before sending - not yet processed by the backend. */
export interface PendingAttachment {
  id: string;
  type: AttachmentType;
  name: string;
  /** Present for image/pdf and file-picker text attachments. */
  file?: File;
  /** Present for pasted-text attachments, which have no underlying File. */
  text?: string;
  /** Image thumbnail object URL. */
  previewUrl?: string;
  /** PDF only, filled in asynchronously once pdfjs finishes counting pages. */
  pageCount?: number;
  /** Text/pasted-text only. */
  charCount?: number;
  preview?: string;
}
