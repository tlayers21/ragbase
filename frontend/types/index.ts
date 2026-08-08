// ── API response shapes ──────────────────────────────────────────────────────

export interface SourceSummary {
  source: string;
  chunk_count: number;
  flagged_count: number;
  contradiction_count: number;
  /** Extension of the stored original (".pdf", ".png", …), "" if no file is stored.
   * Needed to address the file on the Next.js static mount — the source name is a
   * slug and carries no extension. */
  file_ext: string;
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

export type AttachmentType = "image" | "pdf" | "text";

/** Attachment metadata stored on a sent user message. `description` is the VLM
 * output (image) or extracted text (pdf/text) — re-sent in history on every
 * subsequent turn so follow-up questions retain the attachment's context. */
export interface MessageAttachment {
  type: AttachmentType;
  name: string;
  description: string;
  /** Client-side object URL for image thumbnails only — not persisted across reloads. */
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

// ── Chat input attachments (pre-send, client-only) ────────────────────────────

/** An attachment staged in ChatInput before sending — not yet processed by the backend. */
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
