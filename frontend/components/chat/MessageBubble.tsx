"use client";

import { useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { Copy, Check as CheckIcon, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { CURRENT_MODEL } from "./ModelSelector";
import type { CitedChunk, Message } from "@/types";

function CopyButton({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore — clipboard not available in some contexts
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
};

function CitationChip({ chunk, onClick }: { chunk: CitedChunk; onClick: () => void }) {
  const label = chunk.source.length > 22 ? chunk.source.slice(0, 20) + "…" : chunk.source;
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center rounded-full border border-border bg-surface px-2.5 py-0.5 text-[11px] text-foreground-muted hover:border-foreground-muted/40 hover:text-foreground transition-colors"
    >
      {label}
    </button>
  );
}

function ChunkModal({ chunk, onClose }: { chunk: CitedChunk; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/40" />
      <div
        className="relative z-10 w-full max-w-lg rounded-xl border border-border bg-background shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <span className="text-sm font-medium text-foreground truncate pr-4">{chunk.source}</span>
          <div className="flex items-center gap-3 flex-shrink-0">
            <span className="text-xs tabular-nums text-foreground-muted/60">
              {(chunk.score * 100).toFixed(0)}% match
            </span>
            <button
              onClick={onClose}
              className="rounded p-0.5 text-foreground-muted hover:text-foreground transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="overflow-y-auto max-h-80 px-4 py-4">
          <p className="text-sm text-foreground-muted leading-relaxed whitespace-pre-wrap">
            {chunk.text}
          </p>
        </div>
      </div>
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
  return (
    <div className="flex items-center gap-2 h-5">
      <span className="pulse-dot h-2 w-2 rounded-full bg-foreground-muted flex-shrink-0" />
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
  const [openChunk, setOpenChunk] = useState<CitedChunk | null>(null);

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
      className="flex items-start gap-3"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Small avatar dot */}
      <div className="h-6 w-6 flex-shrink-0 mt-0.5 rounded-full bg-foreground-muted/20 flex items-center justify-center">
        <span className="text-[10px] font-semibold text-foreground-muted">R</span>
      </div>
      <div className="flex-1 min-w-0 pb-1">
        {isStreamingEmpty ? (
          <ThinkingIndicator stage={message.stage} />
        ) : (
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
              {message.latencyMs !== undefined && (
                <span className="text-[10px] text-foreground-muted/50">
                  {message.latencyMs < 1000
                    ? `${message.latencyMs}ms`
                    : `${(message.latencyMs / 1000).toFixed(1)}s`}
                </span>
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
            {message.isComplete && message.chunks && message.chunks.length > 0 && (
              <div className="mt-3">
                <p className="text-[10px] font-medium uppercase tracking-wide text-foreground-muted mb-1.5">
                  Sources used
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {message.chunks.map((chunk, i) => (
                    <CitationChip key={i} chunk={chunk} onClick={() => setOpenChunk(chunk)} />
                  ))}
                </div>
                {openChunk && (
                  <ChunkModal chunk={openChunk} onClose={() => setOpenChunk(null)} />
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
