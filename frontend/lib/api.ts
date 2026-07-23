import { DEFAULT_API_URL } from "@/lib/config";
import type { AttachmentType, SourceSummary, IngestionStatus } from "@/types";

// Read runtime overrides from localStorage (set on the settings page).
function getBaseUrl(): string {
  if (typeof window === "undefined") return DEFAULT_API_URL;
  return localStorage.getItem("ragbase_api_url") ?? DEFAULT_API_URL;
}

// ── User settings ────────────────────────────────────────────────────────────

export interface UserSettings {
  user_id: string;
  display_name: string | null;
}

// The backend owns the user identity — fetched once per session and cached.
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

// ── Sources ──────────────────────────────────────────────────────────────────

export function getSourceFileUrl(source: string): string {
  return `${getBaseUrl()}/sources/${encodeURIComponent(source)}/file`;
}

export async function fetchSourceText(source: string): Promise<string> {
  const res = await fetch(getSourceFileUrl(source));
  if (!res.ok) throw new Error(`fetchSourceText: ${res.status}`);
  return res.text();
}

export async function generateChatTitle(message: string): Promise<string> {
  try {
    const res = await fetch(`${getBaseUrl()}/title`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    if (!res.ok) return "";
    const data = await res.json();
    return (data.title as string) ?? "";
  } catch {
    return "";
  }
}

// ── Documents ────────────────────────────────────────────────────────────────

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

// ── Query ────────────────────────────────────────────────────────────────────

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
  onDone: () => void;
}

// Parses SSE frames of the form "data: {token}\n\n", "data: [STAGE]{json}\n\n"
// progress events, "data: [ATTACHMENTS]{json}\n\n" (attachment query only), a
// final "data: [SOURCES]{json}\n\n" citation event, and "data: [DONE]\n\n".
// Shared by streamQuery(), streamDirectQuery(), and streamAttachmentQuery().
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
    if (done) break;
    if (signal?.aborted) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith("data: ")) continue;
      const payload = line.slice("data: ".length);

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
      handlers.onToken(payload);
    }
  }

  if (!signal?.aborted) handlers.onDone();
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

// Bypasses the RAG pipeline entirely — used when the user has deselected
// all sources ("direct LLM mode"). No [STAGE] events are emitted server-side.
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

export interface AttachmentPayload {
  type: AttachmentType;
  name: string;
  /** Present for image/pdf and file-picker text attachments. */
  file?: File;
  /** Present for pasted-text attachments, which have no underlying File. */
  text?: string;
}

// Same RAG/direct routing as streamQuery/streamDirectQuery (controlled by
// isDirect) but sends attachments as multipart and expects an extra
// [ATTACHMENTS] event before generation begins.
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

// ── Ingestion ────────────────────────────────────────────────────────────────

export async function ingestFile(
  file: File,
  sourceName: string
): Promise<{ job_id: string; status: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("source", sourceName);

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

export async function clearCompletedJobs(): Promise<void> {
  const res = await fetch(`${getBaseUrl()}/ingest/clear_completed`, { method: "POST" });
  if (!res.ok) throw new Error(`clearCompletedJobs: ${res.status}`);
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

export async function shouldResetSessions(): Promise<boolean> {
  try {
    const res = await fetch(`${getBaseUrl()}/sessions/should_reset`);
    if (!res.ok) return false;
    const data = await res.json();
    return data.reset === true;
  } catch {
    return false;
  }
}
