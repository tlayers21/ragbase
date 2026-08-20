"use client";

import { useState, useCallback, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { Copy, Check as CheckIcon, X, FileText } from "lucide-react";
import { cn, humanizeSourceName, relevancePercent } from "@/lib/utils";
import { CURRENT_MODEL } from "./ModelSelector";
import type { CitedChunk, Message, MessageAttachment } from "@/types";

function CopyButton({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore - clipboard not available in some contexts
    }
  }, [text]);

  return (
    <button
      onClick={handleCopy}
      className={cn(
        "flex items-center justify-center h-6 w-6 rounded text-foreground-muted hover:text-foreground hover:bg-surface transition-colors",
        className
      )}
      title="Copy message"
    >
      {copied ? (
        <CheckIcon className="h-3.5 w-3.5 text-green-500" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
    </button>
  );
}

const STAGE_LABELS: Record<string, string> = {
  retrieving_sources: "Pulling sources…",
  traversing_graph: "Traversing knowledge graph…",
  reranking: "Reranking chunks…",
  generating: "Generating answer…",
  processing_attachments: "Processing attachments…",
  loading_source: "Reading the document…",
  // Only sent for an oversized source, so it doubles as "this will take a while"
  summarizing_source: "Summarizing the document section by section…",
  stopped: "Stopped.",
};

/** One source's contribution to an answer: its chunks, best score first. */
interface SourceGroup {
  source: string;
  label: string;
  chunks: CitedChunk[];
}

// Grouped by source, because a chip per chunk repeats the same document name
function groupChunksBySource(chunks: CitedChunk[]): SourceGroup[] {
  const bySource = new Map<string, CitedChunk[]>();
  for (const chunk of chunks) {
    const existing = bySource.get(chunk.source);
    if (existing) existing.push(chunk);
    else bySource.set(chunk.source, [chunk]);
  }

  return Array.from(bySource, ([source, sourceChunks]) => ({
    source,
    label: humanizeSourceName(source),
    chunks: [...sourceChunks].sort((a, b) => b.score - a.score),
  })).sort((a, b) => b.chunks[0].score - a.chunks[0].score);
}

function ChunksModal({ group, onClose }: { group: SourceGroup; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/40" />
      <div
        className="relative z-10 w-full max-w-lg rounded-xl border border-border bg-background shadow-xl flex flex-col"
        style={{ maxHeight: "80vh" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex-shrink-0 flex items-center justify-between gap-2 px-4 py-3 border-b border-border">
          <div className="min-w-0">
            <p className="text-sm font-medium text-foreground truncate" title={group.source}>
              {group.label}
            </p>
            <p className="text-[11px] text-foreground-muted">
              {group.chunks.length} chunk{group.chunks.length !== 1 ? "s" : ""} used
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 rounded p-0.5 text-foreground-muted hover:text-foreground transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          {group.chunks.map((chunk, i) => (
            <div key={i} className="rounded-lg border border-border bg-surface p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-foreground truncate">
                  Chunk {i + 1}
                </span>
                <span className="text-[10px] tabular-nums text-foreground-muted/60 flex-shrink-0">
                  {relevancePercent(chunk.score)}% match
                </span>
              </div>
              <p
                className="text-sm text-foreground-muted leading-relaxed whitespace-pre-wrap overflow-y-auto"
                style={{ maxHeight: "200px" }}
              >
                {chunk.text}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// Hover shows the full description through the native title tooltip
function AttachmentChip({ attachment }: { attachment: MessageAttachment }) {
  return (
    <div
      className="inline-flex max-w-[160px] items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1 text-[11px] text-foreground-muted"
      title={attachment.description || "Processing…"}
    >
      {attachment.type === "image" && attachment.previewUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={attachment.previewUrl} alt="" className="h-4 w-4 flex-shrink-0 rounded object-cover" />
      ) : (
        <FileText className="h-3 w-3 flex-shrink-0" />
      )}
      <span className="truncate">{attachment.name}</span>
    </div>
  );
}

function SummaryBlock({ message }: { message: Message }) {
  return (
    <div className="flex justify-center">
      <div className="max-w-xl w-full rounded-lg border border-border bg-surface/50 px-4 py-3">
        <p className="text-[10px] font-medium uppercase tracking-wide text-foreground-muted/50 mb-1.5">
          Earlier conversation summarized
        </p>
        <p className="text-sm italic text-foreground-muted leading-relaxed">{message.content}</p>
      </div>
    </div>
  );
}

function ThinkingIndicator({ stage }: { stage?: string }) {
  const isStopped = stage === "stopped";
  return (
    <div className="flex items-center gap-2 h-5">
      <span
        className={cn(
          "h-2 w-2 rounded-full bg-foreground-muted flex-shrink-0",
          isStopped ? "opacity-60" : "pulse-dot"
        )}
      />
      {stage && (
        <span className="text-xs text-foreground-muted">{STAGE_LABELS[stage] ?? stage}</span>
      )}
    </div>
  );
}

function formatTimestamp(ts: number): string {
  const d = new Date(ts);
  const now = new Date();
  const diffDays = Math.floor(
    (now.setHours(0, 0, 0, 0) - new Date(ts).setHours(0, 0, 0, 0)) / 86_400_000
  );
  const time = new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (diffDays === 0) return `Today at ${time}`;
  if (diffDays === 1) return `Yesterday at ${time}`;
  const dateStr = d.toLocaleDateString([], { month: "short", day: "numeric" });
  return `${dateStr} at ${time}`;
}

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const [isHovered, setIsHovered] = useState(false);
  const [openSource, setOpenSource] = useState<string | null>(null);
  // Must run before the early returns below - hooks can't be conditional
  const sourceGroups = useMemo(() => groupChunksBySource(message.chunks ?? []), [message.chunks]);
  const openGroup = sourceGroups.find((g) => g.source === openSource) ?? null;

  if (message.role === "system" && message.type === "summary") {
    return <SummaryBlock message={message} />;
  }

  if (isUser) {
    return (
      <div
        className="flex justify-end"
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        <div className="relative max-w-[75%]">
          <div className="rounded-2xl rounded-tr-sm bg-surface border border-border px-4 py-2.5 text-sm text-foreground whitespace-pre-wrap">
            {message.content}
          </div>
          {message.attachments && message.attachments.length > 0 && (
            <div className="mt-1.5 flex flex-wrap justify-end gap-1.5">
              {message.attachments.map((a, i) => (
                <AttachmentChip key={i} attachment={a} />
              ))}
            </div>
          )}
          <div
            className={cn(
              "flex items-center justify-end gap-1.5 mt-1 transition-opacity duration-150",
              isHovered ? "opacity-100" : "opacity-0"
            )}
          >
            <span className="text-[10px] text-foreground-muted/60 whitespace-nowrap">
              {formatTimestamp(message.timestamp)}
            </span>
            <CopyButton text={message.content} />
          </div>
        </div>
      </div>
    );
  }

  const isStreamingEmpty = message.content.length === 0;
  const modeBadgeLabel = `${CURRENT_MODEL} · ${message.mode === "direct" ? "direct" : "RAG"}`;

  return (
    <div
      className="flex items-start gap-3 pl-2"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className="flex-1 min-w-0 pb-1">
        {/* The indicator is shown alongside the answer, not instead of it.
            Making the two exclusive on `content.length === 0` meant the first
            token unmounted the stage line, so a stage was only ever visible if a
            multi-second blocking step followed it. `generating` is the one stage
            whose successor is the token stream: measured on the wire, the gap
            between the [STAGE] frame and the first token is 163ms on a cache hit
            and 355ms in direct mode - far too short to read, and when both land
            in one reader.read() React batches them and it never paints at all.
            `retrieving_sources` had the same problem whenever a graph exists,
            since `traversing_graph` follows it 190ms later.

            Keyed on `isComplete` instead: the stage line stays up for the whole
            generating phase and disappears when the answer is finished.

            `|| isStreamingEmpty` keeps one case the old condition covered on its
            own: a stream stopped before its first token. `useChat` calls
            `onDone()` (which sets isComplete) *before* writing `stage:
            "stopped"`, so that message is complete-but-empty, and on
            `!isComplete` alone it would render as a blank bubble instead of the
            permanent "Stopped." the stop button is supposed to leave behind. */}
        {(!message.isComplete || isStreamingEmpty) && (
          <div className="mb-2">
            <ThinkingIndicator stage={message.stage} />
          </div>
        )}
        {!isStreamingEmpty && (
          <div className="markdown-body text-sm text-foreground leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
              {message.content}
            </ReactMarkdown>
          </div>
        )}
        {/* Model badge + latency + copy */}
        {!isStreamingEmpty && (
          <>
            <div className="mt-2 flex items-center gap-2">
              <span className="text-[10px] text-foreground-muted/60">{modeBadgeLabel}</span>
              {message.stage === "stopped" ? (
                <span className="text-[10px] text-foreground-muted/50">stopped</span>
              ) : (
                // Undefined until the post-paint measurement lands, and never on a stop
                message.latencyMs !== undefined && (
                  <span className="text-[10px] text-foreground-muted/50">
                    {message.latencyMs < 1000
                      ? `${message.latencyMs}ms`
                      : `${(message.latencyMs / 1000).toFixed(1)}s`}
                  </span>
                )
              )}
              <div
                className={cn(
                  "flex items-center gap-1.5 ml-auto transition-opacity duration-150",
                  isHovered ? "opacity-100" : "opacity-0"
                )}
              >
                <span className="text-[10px] text-foreground-muted/50 whitespace-nowrap">
                  {formatTimestamp(message.timestamp)}
                </span>
                <CopyButton text={message.content} />
              </div>
            </div>
            {message.isComplete && sourceGroups.length > 0 && (
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] text-foreground-muted/60 mr-0.5">Sources used</span>
                {sourceGroups.map((group) => (
                  <button
                    key={group.source}
                    onClick={() => setOpenSource(group.source)}
                    title={`${group.source} - ${group.chunks.length} chunk${group.chunks.length !== 1 ? "s" : ""}`}
                    className="inline-flex max-w-[220px] items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-0.5 text-[11px] text-foreground-muted hover:border-foreground-muted/40 hover:text-foreground transition-colors"
                  >
                    <span className="truncate">{group.label}</span>
                    <span className="tabular-nums text-foreground-muted/60">
                      {group.chunks.length}
                    </span>
                  </button>
                ))}
                {openGroup && (
                  <ChunksModal group={openGroup} onClose={() => setOpenSource(null)} />
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
