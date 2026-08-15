"use client";

import { useEffect, useRef } from "react";
import { Files } from "lucide-react";
import { MessageBubble } from "./MessageBubble";
import { ChatInput } from "./ChatInput";
import { SourceFilter } from "./SourceFilter";
import { ModelSelector } from "./ModelSelector";
import { IngestionBanner } from "./IngestionBanner";
import type { ChatSession, IngestionJob, PendingAttachment, SourceSummary } from "@/types";

interface ChatAreaProps {
  session: ChatSession | null;
  isLoading: boolean;
  isStreaming: boolean;
  error: string | null;
  sources: SourceSummary[];
  selectedSources: Set<string>;
  buildingGraphSources: Set<string>;
  /** Jobs actively consuming the machine — drives the warning banner. */
  ingestingJobs: IngestionJob[];
  onToggleSource: (source: string) => void;
  onSelectAllSources: () => void;
  onClearAllSources: () => void;
  onSend: (content: string, attachments: PendingAttachment[]) => void;
  onStop: () => void;
  onOpenSourcesModal: () => void;
}

function EmptyState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center">
      <h2 className="text-xl font-semibold text-foreground">Ask your knowledge base</h2>
      <p className="text-sm text-foreground-muted max-w-xs">
        Ask anything. RAGbase retrieves answers from your ingested documents.
      </p>
    </div>
  );
}

export function ChatArea({
  session,
  isLoading,
  isStreaming,
  error,
  sources,
  selectedSources,
  buildingGraphSources,
  ingestingJobs,
  onToggleSource,
  onSelectAllSources,
  onClearAllSources,
  onSend,
  onStop,
  onOpenSourcesModal,
}: ChatAreaProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.messages, isLoading]);

  const messages = session?.messages ?? [];

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Above the top bar, outside the scroll container: the whole point is that
          it can't be scrolled past or collapsed away like the ingest panel can. */}
      <IngestionBanner jobs={ingestingJobs} />

      {/* Thin top bar with Sources button */}
      <div className="flex items-center justify-end px-4 py-1.5 border-b border-border flex-shrink-0">
        <button
          onClick={onOpenSourcesModal}
          className="flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs text-foreground-muted hover:text-foreground hover:bg-surface transition-colors"
          title="Browse ingested sources"
        >
          <Files className="h-3.5 w-3.5" />
          <span>Sources{sources.length > 0 ? ` (${sources.length})` : ""}</span>
        </button>
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="mx-auto max-w-3xl px-4 py-6 space-y-6">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
            {error && (
              <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                Error: {error}
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Source filter row — ModelSelector sits on the right */}
      <SourceFilter
        sources={sources}
        selectedSources={selectedSources}
        buildingGraphSources={buildingGraphSources}
        rightSlot={<ModelSelector />}
        onToggle={onToggleSource}
        onSelectAll={onSelectAllSources}
        onClearAll={onClearAllSources}
      />

      <ChatInput onSend={onSend} onStop={onStop} isStreaming={isStreaming} isLoading={isLoading} />
    </div>
  );
}
