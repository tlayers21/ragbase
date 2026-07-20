import { DEFAULT_API_URL, DEFAULT_USER_ID } from "@/lib/config";
import type {
  QueryResponse,
  SourceSummary,
  ChunkDetail,
  IngestionStatus,
} from "@/types";

// Read runtime overrides from localStorage (set on the settings page).
function getBaseUrl(): string {
  if (typeof window === "undefined") return DEFAULT_API_URL;
  return localStorage.getItem("ragbase_api_url") ?? DEFAULT_API_URL;
}

export function getUserId(): string {
  if (typeof window === "undefined") return DEFAULT_USER_ID;
  return localStorage.getItem("ragbase_user_id") ?? DEFAULT_USER_ID;
}

// ── Sources ──────────────────────────────────────────────────────────────────

export function getSourceFileUrl(source: string): string {
  return `${getBaseUrl()}/sources/${encodeURIComponent(source)}/file?user_id=${getUserId()}`;
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
  const res = await fetch(
    `${getBaseUrl()}/documents/?user_id=${getUserId()}`
  );
  if (!res.ok) throw new Error(`fetchSources: ${res.status}`);
  return res.json();
}

export async function fetchChunks(source: string): Promise<ChunkDetail[]> {
  const res = await fetch(
    `${getBaseUrl()}/documents/${encodeURIComponent(source)}?user_id=${getUserId()}`
  );
  if (!res.ok) throw new Error(`fetchChunks: ${res.status}`);
  return res.json();
}

export async function deleteSource(source: string): Promise<void> {
  const res = await fetch(
    `${getBaseUrl()}/documents/${encodeURIComponent(source)}?user_id=${getUserId()}`,
    { method: "DELETE" }
  );
  if (!res.ok) throw new Error(`deleteSource: ${res.status}`);
}

// ── Query ────────────────────────────────────────────────────────────────────

export async function sendQuery(
  question: string,
  history: { role: string; content: string }[] = [],
  sourceFilter: string[] | null = null
): Promise<QueryResponse> {
  const res = await fetch(`${getBaseUrl()}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      user_id: getUserId(),
      history,
      source_filter: sourceFilter,
    }),
  });
  if (!res.ok) throw new Error(`sendQuery: ${res.status}`);
  return res.json();
}

export interface StreamQueryHandlers {
  onStage?: (stage: string) => void;
  onToken: (token: string) => void;
  onSources: (sources: string[], scores: number[], chunks: import("@/types").CitedChunk[]) => void;
  onDone: () => void;
}

// Parses SSE frames of the form "data: {token}\n\n", "data: [STAGE]{json}\n\n"
// progress events, a final "data: [SOURCES]{json}\n\n" citation event, and
// "data: [DONE]\n\n". Shared by streamQuery() and streamDirectQuery().
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
      user_id: getUserId(),
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
      user_id: getUserId(),
      history,
      source_filter: null,
    }),
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
  form.append("user_id", getUserId());

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

export async function compactMessages(
  messages: { role: string; content: string }[],
  userId: string
): Promise<string> {
  const res = await fetch(`${getBaseUrl()}/compact`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, user_id: userId }),
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
