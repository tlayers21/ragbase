import { DEFAULT_API_URL } from "@/lib/config";
import type { AttachmentType, HealthStatus, SourceSummary, IngestionStatus } from "@/types";

// Read runtime overrides from localStorage (set on the settings page)
function getBaseUrl(): string {
  if (typeof window === "undefined") return DEFAULT_API_URL;
  return localStorage.getItem("ragbase_api_url") ?? DEFAULT_API_URL;
}

// -- User settings ------------------------------------------------------------

export interface UserSettings {
  user_id: string;
  display_name: string | null;
  /** Retrieval relevance floor in raw reranker logits, not a percentage. */
  reranker_min_score: number;
}

// The backend owns the user identity - fetched once per session and cached
let cachedUserSettings: UserSettings | null = null;

export async function fetchUserSettings(force = false): Promise<UserSettings> {
  if (cachedUserSettings && !force) return cachedUserSettings;
  const res = await fetch(`${getBaseUrl()}/settings/user`);
  if (!res.ok) throw new Error(`fetchUserSettings: ${res.status}`);
  cachedUserSettings = (await res.json()) as UserSettings;
  return cachedUserSettings;
}

export async function saveDisplayName(displayName: string): Promise<void> {
  const res = await fetch(`${getBaseUrl()}/settings/display_name`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: displayName }),
  });
  if (!res.ok) throw new Error(`saveDisplayName: ${res.status}`);
  if (cachedUserSettings) {
    cachedUserSettings = { ...cachedUserSettings, display_name: displayName.trim() || null };
  }
}

export async function setTelemetryEnabled(enabled: boolean): Promise<void> {
  const res = await fetch(`${getBaseUrl()}/settings/telemetry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!res.ok) throw new Error(`setTelemetryEnabled: ${res.status}`);
}

/**
 * Set the relevance floor in raw reranker logits, not the displayed percentage.
 *
 * Applies to the next query, and the server clears the semantic cache too.
 */
export async function setRerankerThreshold(minScore: number): Promise<void> {
  const res = await fetch(`${getBaseUrl()}/settings/reranker_threshold`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ min_score: minScore }),
  });
  if (!res.ok) throw new Error(`setRerankerThreshold: ${res.status}`);
  if (cachedUserSettings) {
    cachedUserSettings = { ...cachedUserSettings, reranker_min_score: minScore };
  }
}

// -- Health / warmup ----------------------------------------------------------

/**
 * Backend liveness and startup warmup progress.
 *
 * `cache: "no-store"` matters - this is polled in a loop and a cached "ready:
 * false" would leave the UI gated after warmup finished.
 */
export async function fetchHealth(): Promise<HealthStatus> {
  const res = await fetch(`${getBaseUrl()}/health`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchHealth: ${res.status}`);
  return (await res.json()) as HealthStatus;
}

// -- Sources ------------------------------------------------------------------

export function getSourceFileUrl(source: string): string {
  return `${getBaseUrl()}/sources/${encodeURIComponent(source)}/file`;
}

/**
 * Same-origin URL for a stored source file, off the Next.js static route.
 *
 * Returns null when the extension is unknown, so callers fall back to
 * getSourceFileUrl().
 */
export async function getStaticSourceFileUrl(
  source: string,
  fileExt: string
): Promise<string | null> {
  if (!fileExt) return null;
  try {
    // Cached after the first call - this does not re-hit the backend per source
    const { user_id } = await fetchUserSettings();
    return `/static/sources/${encodeURIComponent(user_id)}/${encodeURIComponent(source)}${fileExt}`;
  } catch {
    return null;
  }
}

export async function fetchTextFile(url: string, signal?: AbortSignal): Promise<string> {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`fetchTextFile: ${res.status}`);
  return res.text();
}

export async function fetchSourceText(source: string, signal?: AbortSignal): Promise<string> {
  return fetchTextFile(getSourceFileUrl(source), signal);
}

// HEADs the stored file - the extension is not recoverable from the source slug
export async function fetchSourceType(
  source: string,
  signal?: AbortSignal
): Promise<"pdf" | "image" | "text"> {
  const res = await fetch(getSourceFileUrl(source), { method: "HEAD", signal });
  if (!res.ok) throw new Error(`${res.status}`);
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("pdf")) return "pdf";
  if (contentType.startsWith("image/")) return "image";
  return "text";
}

export async function generateChatTitle(message: string): Promise<string> {
  const res = await fetch(`${getBaseUrl()}/title`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  // Throws rather than returning "" - "" means the model produced no title
  if (!res.ok) throw new Error(`generateChatTitle: ${res.status}`);
  const data = await res.json();
  return (data.title as string) ?? "";
}

// -- Documents ----------------------------------------------------------------

export async function fetchSources(): Promise<SourceSummary[]> {
  const res = await fetch(`${getBaseUrl()}/documents/`);
  if (!res.ok) throw new Error(`fetchSources: ${res.status}`);
  return res.json();
}

export async function deleteSource(source: string): Promise<void> {
  const res = await fetch(`${getBaseUrl()}/documents/${encodeURIComponent(source)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`deleteSource: ${res.status}`);
}

// -- Query --------------------------------------------------------------------

export interface AttachmentResult {
  type: AttachmentType;
  name: string;
  description: string;
}

export interface StreamQueryHandlers {
  onStage?: (stage: string) => void;
  onToken: (token: string) => void;
  onSources: (sources: string[], scores: number[], chunks: import("@/types").CitedChunk[]) => void;
  /** Fired once for /query/with_attachments after attachments are processed server-side. */
  onAttachments?: (attachments: AttachmentResult[]) => void;
  /** The backend's own elapsed time for this request, in ms, delivered just before
   * [DONE]. Half of the end-to-end latency figure - the caller adds its own time
   * from here to final paint. */
  onTiming?: (serverMs: number) => void;
  onDone: () => void;
}

// The one SSE parser, shared by every streaming call and matched to _sse_token
async function consumeQueryStream(
  res: Response,
  handlers: StreamQueryHandlers,
  signal?: AbortSignal
): Promise<void> {
  if (!res.ok || !res.body) throw new Error(`query stream: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  signal?.addEventListener("abort", () => reader.cancel());

  while (true) {
    const { done, value } = await reader.read();
    // reader.cancel() resolves read() with done:true rather than rejecting, so re-throw
    if (done) break;
    if (signal?.aborted) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      // Never trim the payload - a " " token becomes "" and words run together
      const line = frame.replace(/^\n+/, "").replace(/\r$/, "");
      if (!line.startsWith("data:")) continue;
      // Per the SSE spec a single space after "data:" is framing, not content
      const payload = line.startsWith("data: ")
        ? line.slice("data: ".length)
        : line.slice("data:".length);

      if (payload === "[HEARTBEAT]") continue;
      if (payload === "[DONE]") {
        handlers.onDone();
        return;
      }
      if (payload.startsWith("[SOURCES]")) {
        try {
          const { sources, scores, chunks = [] } = JSON.parse(payload.slice("[SOURCES]".length));
          handlers.onSources(sources, scores, chunks);
        } catch {
          // ignore malformed sources payload
        }
        continue;
      }
      if (payload.startsWith("[ATTACHMENTS]")) {
        try {
          const { attachments } = JSON.parse(payload.slice("[ATTACHMENTS]".length));
          handlers.onAttachments?.(attachments);
        } catch {
          // ignore malformed attachments payload
        }
        continue;
      }
      if (payload.startsWith("[STAGE]")) {
        try {
          const { stage } = JSON.parse(payload.slice("[STAGE]".length));
          handlers.onStage?.(stage);
        } catch {
          // ignore malformed stage payload
        }
        continue;
      }
      if (payload.startsWith("[TIMING]")) {
        try {
          const { server_ms } = JSON.parse(payload.slice("[TIMING]".length));
          if (typeof server_ms === "number") handlers.onTiming?.(server_ms);
        } catch {
          // Ignore a malformed timing payload - the latency badge is cosmetic
        }
        continue;
      }
      // Every control frame was matched above, so anything here is a JSON token
      try {
        handlers.onToken(JSON.parse(payload) as string);
      } catch {
        // Tolerate an un-encoded payload rather than dropping the token
        handlers.onToken(payload);
      }
    }
  }

  if (signal?.aborted) {
    throw new DOMException("The user aborted a request.", "AbortError");
  }
  handlers.onDone();
}

export async function streamQuery(
  question: string,
  history: { role: string; content: string }[],
  sourceFilter: string[] | null,
  handlers: StreamQueryHandlers,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(`${getBaseUrl()}/query/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      history,
      source_filter: sourceFilter,
    }),
    signal,
  });
  await consumeQueryStream(res, handlers, signal);
}

// Bypasses retrieval entirely, emitting only the `generating` stage
export async function streamDirectQuery(
  question: string,
  history: { role: string; content: string }[],
  handlers: StreamQueryHandlers,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(`${getBaseUrl()}/query/direct`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      history,
      source_filter: null,
    }),
    signal,
  });
  await consumeQueryStream(res, handlers, signal);
}

/**
 * Explain one source in depth. No question, no history and no source_filter:
 * the server uses every chunk of `source` in document order and does no ranking,
 * so the only thing it needs is the name.
 */
export async function streamExplainSource(
  source: string,
  handlers: StreamQueryHandlers,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(`${getBaseUrl()}/query/explain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source }),
    signal,
  });
  await consumeQueryStream(res, handlers, signal);
}

export interface AttachmentPayload {
  type: AttachmentType;
  name: string;
  /** Present for image/pdf and file-picker text attachments. */
  file?: File;
  /** Present for pasted-text attachments, which have no underlying File. */
  text?: string;
}

// Same routing as streamQuery, but multipart and with an extra [ATTACHMENTS] frame
export async function streamAttachmentQuery(
  question: string,
  history: { role: string; content: string }[],
  sourceFilter: string[] | null,
  isDirect: boolean,
  attachments: AttachmentPayload[],
  handlers: StreamQueryHandlers,
  signal?: AbortSignal
): Promise<void> {
  const form = new FormData();
  form.append("question", question);
  form.append("history", JSON.stringify(history));
  form.append("source_filter", sourceFilter ? JSON.stringify(sourceFilter) : "");
  form.append("is_direct", String(isDirect));
  for (const a of attachments) {
    const file = a.file ?? new File([a.text ?? ""], a.name, { type: "text/plain" });
    form.append("attachments", file, a.name);
  }

  const res = await fetch(`${getBaseUrl()}/query/with_attachments`, {
    method: "POST",
    body: form,
    signal,
  });
  await consumeQueryStream(res, handlers, signal);
}

// -- Ingestion ----------------------------------------------------------------

export async function ingestFile(
  file: File,
  sourceName: string,
  describeImages = false
): Promise<{ job_id: string; status: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("source", sourceName);
  // PDFs only - every other format ignores it server-side
  form.append("describe_images", String(describeImages));

  const res = await fetch(`${getBaseUrl()}/ingest/file`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`ingestFile: ${res.status}`);
  return res.json();
}

export async function fetchIngestionStatus(): Promise<IngestionStatus> {
  const res = await fetch(`${getBaseUrl()}/ingest/status`);
  if (!res.ok) throw new Error(`fetchIngestionStatus: ${res.status}`);
  return res.json();
}

export async function cancelIngestion(jobId: string): Promise<void> {
  const res = await fetch(
    `${getBaseUrl()}/ingest/cancel/${encodeURIComponent(jobId)}`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error(`cancelIngestion: ${res.status}`);
}

export async function ingestText(
  text: string,
  sourceName: string
): Promise<{ job_id: string; status: string }> {
  const form = new FormData();
  form.append("text", text);
  form.append("source", sourceName);
  const res = await fetch(`${getBaseUrl()}/ingest/text`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`ingestText: ${res.status}`);
  return res.json();
}

export async function ingestUrl(
  url: string
): Promise<{ job_id: string; status: string; source: string }> {
  const form = new FormData();
  form.append("url", url);
  const res = await fetch(`${getBaseUrl()}/ingest/url`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`ingestUrl: ${res.status}`);
  return res.json();
}

export async function generateTitle(text: string): Promise<string> {
  const form = new FormData();
  form.append("text", text);
  const res = await fetch(`${getBaseUrl()}/ingest/generate_title`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`generateTitle: ${res.status}`);
  const data = await res.json();
  return (data.title as string) ?? "";
}

export async function compactMessages(
  messages: { role: string; content: string }[]
): Promise<string> {
  const res = await fetch(`${getBaseUrl()}/compact`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });
  if (!res.ok) throw new Error(`compactMessages: ${res.status}`);
  const data = await res.json();
  return (data.summary as string) ?? "";
}

/**
 * Timestamp of the most recent reset_all.sh run, or null if never reset.
 *
 * Throws when the backend is unreachable, and that distinction is the point:
 * null is a real answer, a throw means retry.
 */
export async function fetchResetToken(): Promise<number | null> {
  const res = await fetch(`${getBaseUrl()}/sessions/should_reset`);
  if (!res.ok) throw new Error(`fetchResetToken: ${res.status}`);
  const data = await res.json();
  return typeof data.reset_at === "number" ? data.reset_at : null;
}
