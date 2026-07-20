"use client";

import { useEffect, useCallback } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ChunkDetail } from "@/types";

interface ChunkModalProps {
  isOpen: boolean;
  sourceName: string;
  score?: number;
  chunks: ChunkDetail[];
  isLoading: boolean;
  onClose: () => void;
}

export function ChunkModal({
  isOpen,
  sourceName,
  score,
  chunks,
  isLoading,
  onClose,
}: ChunkModalProps) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose]
  );

  useEffect(() => {
    if (!isOpen) return;
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, handleKeyDown]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={`Chunks from ${sourceName}`}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="relative z-10 flex flex-col bg-surface-raised border border-border rounded-xl shadow-2xl w-full max-w-2xl max-h-[80vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border flex-shrink-0">
          <div>
            <h2 className="font-semibold text-foreground truncate">
              📄 {sourceName}
            </h2>
            {score !== undefined && (
              <p className="text-xs text-foreground-muted mt-0.5">
                Reranker score: {score.toFixed(3)}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-foreground-muted hover:text-foreground hover:bg-surface transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto p-5 space-y-4">
          {isLoading ? (
            <div className="flex justify-center py-8">
              <div className="flex gap-1">
                <span className="loading-dot h-2 w-2 rounded-full bg-foreground-muted" />
                <span className="loading-dot h-2 w-2 rounded-full bg-foreground-muted" />
                <span className="loading-dot h-2 w-2 rounded-full bg-foreground-muted" />
              </div>
            </div>
          ) : chunks.length === 0 ? (
            <p className="text-center text-sm text-foreground-muted py-8">
              No chunks found.
            </p>
          ) : (
            chunks.map((chunk) => (
              <div
                key={chunk.chunk_index}
                className={cn(
                  "rounded-lg border p-4 text-sm",
                  chunk.flagged
                    ? "border-yellow-400/40 bg-yellow-500/5"
                    : "border-border bg-surface"
                )}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-foreground-muted">
                    Chunk {chunk.chunk_index + 1}
                  </span>
                  {chunk.flagged && (
                    <span className="text-[10px] font-medium text-yellow-600 dark:text-yellow-400 bg-yellow-500/10 px-2 py-0.5 rounded-full">
                      ⚠ Flagged
                    </span>
                  )}
                </div>
                <p className="text-foreground leading-relaxed whitespace-pre-wrap font-mono text-xs">
                  {chunk.text}
                </p>
                {chunk.flag_reason && (
                  <p className="mt-2 text-xs text-yellow-600 dark:text-yellow-400">
                    {chunk.flag_reason}
                  </p>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
