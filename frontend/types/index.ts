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

/** One chunk of a source, with whatever the two analysis checks wrote onto it.
 *  `flagged`/`contradiction` are false and the reasons empty until a check runs -
 *  there is no "not checked yet" state in the metadata, so an all-false source
 *  and an unchecked one look identical here. The card's counts say which. */
export interface ChunkDetail {
  chunk_index: number;
  text: string;
  flagged: boolean;
  flag_reason: string;
  contradiction: boolean;
  contradiction_reason: string;
  contradicts_source: string;
}

/** Which of the two per-source checks a run is: general factual accuracy, or
 *  disagreement against every other ingested source. */
export type AnalysisKind = "facts" | "contradictions";

/** The single analysis run in flight, process-wide - only one can hold the slot,
 *  because both checks drive the same Ollama that answers queries. */
export interface AnalysisRun {
  source: string;
  kind: AnalysisKind;
  /** Chunks of the source, not model calls: contradictions makes up to five per chunk. */
  current: number;
  total: number;
  /** Flagged chunks or contradictions found so far, whichever check this is. */
  found: number;
  cancelled: boolean;
  elapsed_seconds: number;
}

export interface AnalysisStatus {
  run: AnalysisRun | null;
}

/** What a finished check reports back. `checked` is below `total` only when the
 *  run was cancelled part way, and whatever it wrote before that stays. */
export interface AnalysisResult {
  source: string;
  kind: AnalysisKind;
  found: number;
  checked: number;
  total: number;
  cancelled: boolean;
}

/** The status lifecycle of an ingestion job, in order, where `done` means
 *  extraction and the graph build both finished. A failure is the literal
 *  string `error: <detail>`, which consumers prefix-match. */
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
  /** Countable progress through the current phase, where the phase has a
   *  countable loop. Absent everywhere else, so consumers fall back to
   *  `estimated_seconds`. */
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
  /** End-to-end latency in ms, from API receipt to this answer's final paint.
   *  Two deltas on two clocks, added, so no clock is compared across the two. */
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
