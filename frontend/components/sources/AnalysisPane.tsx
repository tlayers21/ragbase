"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  ChevronLeft,
  GitCompare,
  Loader2,
  ShieldCheck,
} from "lucide-react";
import { fetchSourceChunks } from "@/lib/api";
import { cn, humanizeSourceName } from "@/lib/utils";
import type { AnalysisKind, AnalysisResult, AnalysisRun, ChunkDetail, SourceSummary } from "@/types";

/** What `useAnalysis()` hands back. Declared here so the pane needs no hook import. */
export interface AnalysisController {
  run: AnalysisRun | null;
  result: AnalysisResult | null;
  error: string | null;
  start: (source: string, kind: AnalysisKind) => Promise<void>;
  stop: () => Promise<void>;
  dismissResult: () => void;
}

const KIND_LABELS: Record<AnalysisKind, string> = {
  facts: "Fact check",
  contradictions: "Contradiction check",
};

// Singular so the summary line reads "3 flagged chunks" / "3 contradictions"
const KIND_FINDINGS: Record<AnalysisKind, string> = {
  facts: "flagged chunk",
  contradictions: "contradiction",
};

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

// -- Running state -------------------------------------------------------------

/**
 * The progress bar for a run in flight.
 *
 * `total` is 0 for the moment between the optimistic start and the backend
 * reporting the chunk count, which renders as an indeterminate pulse rather than
 * a bar pinned at 0% - the latter reads as "stuck" during the slowest part.
 */
function RunProgress({
  run,
  isThisSource,
  onStop,
}: {
  run: AnalysisRun;
  isThisSource: boolean;
  onStop: () => void;
}) {
  const percent = run.total > 0 ? Math.min(100, (run.current / run.total) * 100) : 0;
  const label = KIND_LABELS[run.kind] ?? run.kind;

  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2.5">
      <div className="flex items-center gap-2">
        <Loader2 className="h-3.5 w-3.5 flex-shrink-0 animate-spin text-foreground-muted" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-medium text-foreground">
            {label}
            {!isThisSource && (
              // Named, because the buttons below are disabled and this says why
              <span className="font-normal text-foreground-muted">
                {" "}
                on {humanizeSourceName(run.source)}
              </span>
            )}
          </p>
          <p className="text-[10px] text-foreground-muted">
            {run.total > 0 ? `Chunk ${run.current} of ${run.total}` : "Counting chunks…"}
            {run.found > 0 && ` · ${plural(run.found, KIND_FINDINGS[run.kind] ?? "finding")}`}
            {run.cancelled && " · stopping after this chunk"}
          </p>
        </div>
        {isThisSource && !run.cancelled && (
          <button
            onClick={onStop}
            className="flex-shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium text-foreground-muted transition-colors hover:text-destructive"
            title="Stop after the current chunk"
          >
            Stop
          </button>
        )}
      </div>

      <div className="mt-2 h-1 overflow-hidden rounded-full bg-surface-raised">
        <div
          className={cn(
            "h-full rounded-full bg-blue-500 transition-[width] duration-500 ease-out",
            run.total === 0 && "w-1/3 animate-pulse"
          )}
          style={run.total > 0 ? { width: `${percent}%` } : undefined}
        />
      </div>
    </div>
  );
}

// -- Findings on one chunk -----------------------------------------------------

function Finding({
  tone,
  title,
  reason,
}: {
  tone: "amber" | "red";
  title: string;
  reason: string;
}) {
  return (
    <div
      className={cn(
        "mt-1.5 rounded-md border px-2 py-1.5",
        tone === "amber" ? "border-amber-500/30 bg-amber-500/10" : "border-red-500/30 bg-red-500/10"
      )}
    >
      <p
        className={cn(
          "flex items-center gap-1 text-[11px] font-medium",
          tone === "amber" ? "text-amber-600" : "text-red-500"
        )}
      >
        <AlertTriangle className="h-3 w-3 flex-shrink-0" />
        {title}
      </p>
      {/* The model's own words - it wrote the reason, so it explains the verdict */}
      <p className="mt-0.5 text-[11px] leading-snug text-foreground">{reason}</p>
    </div>
  );
}

const CHUNK_PREVIEW_CHARS = 220;

function ChunkRow({ chunk }: { chunk: ChunkDetail }) {
  const [expanded, setExpanded] = useState(false);
  const isLong = chunk.text.length > CHUNK_PREVIEW_CHARS;
  const hasIssue = chunk.flagged || chunk.contradiction;

  return (
    <div
      className={cn(
        "rounded-lg border p-2.5",
        hasIssue ? "border-border bg-surface" : "border-border/50 bg-transparent"
      )}
    >
      <div className="mb-1 flex items-center gap-2">
        <span className="text-[10px] font-medium uppercase tracking-wide text-foreground-muted/60">
          Chunk {chunk.chunk_index + 1}
        </span>
        {chunk.flagged && (
          <span className="rounded bg-amber-500/15 px-1.5 py-px text-[10px] font-medium text-amber-600">
            Flagged
          </span>
        )}
        {chunk.contradiction && (
          <span className="rounded bg-red-500/15 px-1.5 py-px text-[10px] font-medium text-red-500">
            Contradiction
          </span>
        )}
      </div>

      <p className="whitespace-pre-wrap text-[11px] leading-relaxed text-foreground-muted">
        {expanded || !isLong ? chunk.text : `${chunk.text.slice(0, CHUNK_PREVIEW_CHARS)}…`}
      </p>
      {isLong && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 text-[10px] text-foreground-muted transition-colors hover:text-foreground"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}

      {chunk.flagged && (
        <Finding
          tone="amber"
          title="Possible factual error"
          reason={chunk.flag_reason || "No reason recorded."}
        />
      )}
      {chunk.contradiction && (
        <Finding
          tone="red"
          title={
            chunk.contradicts_source
              ? `Contradicts ${humanizeSourceName(chunk.contradicts_source)}`
              : "Contradicts another source"
          }
          reason={chunk.contradiction_reason || "No reason recorded."}
        />
      )}
    </div>
  );
}

// -- The pane ------------------------------------------------------------------

interface AnalysisPaneProps {
  source: SourceSummary;
  analysis: AnalysisController;
  /** Bumped whenever a run ends, so the chunk list picks up what it wrote. */
  reloadToken: number;
  onBack: () => void;
}

/**
 * Run the two checks over one source, and read what they found.
 *
 * This is the only place the per-chunk verdicts are visible: the checks write
 * `flagged`/`contradiction` into each chunk's ChromaDB metadata and nothing in
 * retrieval reads them, so without a view like this the endpoints produce
 * numbers on a card and nothing else.
 */
export function AnalysisPane({ source, analysis, reloadToken, onBack }: AnalysisPaneProps) {
  const [chunks, setChunks] = useState<ChunkDetail[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [onlyIssues, setOnlyIssues] = useState(false);

  const { run, result, error, start, stop, dismissResult } = analysis;
  const isRunningHere = run?.source === source.source;
  const isBusyElsewhere = Boolean(run) && !isRunningHere;

  useEffect(() => {
    // Aborted on unmount, or a late failure paints an error over a closed pane
    const controller = new AbortController();
    setIsLoading(true);
    setLoadError(null);

    fetchSourceChunks(source.source, controller.signal)
      .then((data) => {
        setChunks(data);
        setIsLoading(false);
      })
      .catch((err: Error) => {
        if (err.name === "AbortError") return;
        setLoadError(err.message);
        setIsLoading(false);
      });

    return () => controller.abort();
  }, [source.source, reloadToken]);

  const issueCount = useMemo(
    () => chunks.filter((c) => c.flagged || c.contradiction).length,
    [chunks]
  );

  const visible = useMemo(
    () => (onlyIssues ? chunks.filter((c) => c.flagged || c.contradiction) : chunks),
    [chunks, onlyIssues]
  );

  const runCheck = useCallback(
    (kind: AnalysisKind) => {
      dismissResult();
      void start(source.source, kind);
    },
    [dismissResult, source.source, start]
  );

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex flex-shrink-0 items-center gap-2 border-b border-border px-4 py-3">
        <button
          onClick={onBack}
          className="rounded p-1 text-foreground-muted transition-colors hover:text-foreground"
          title="Back to sources"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <ShieldCheck className="h-4 w-4 flex-shrink-0 text-foreground-muted" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">{source.source}</p>
          <p className="text-[11px] text-foreground-muted">
            {plural(source.chunk_count, "chunk")}
            {issueCount > 0 && ` · ${plural(issueCount, "chunk")} with findings`}
          </p>
        </div>
      </div>

      {/* Controls */}
      <div className="flex-shrink-0 space-y-2 border-b border-border px-3 py-2.5">
        {run ? (
          <RunProgress run={run} isThisSource={isRunningHere} onStop={() => void stop()} />
        ) : (
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => runCheck("facts")}
              disabled={isBusyElsewhere}
              className="flex items-center justify-center gap-1.5 rounded-lg border border-border bg-surface px-2 py-2 text-xs font-medium text-foreground transition-colors hover:border-border/80 hover:bg-surface-raised disabled:cursor-not-allowed disabled:opacity-50"
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              Fact check
            </button>
            <button
              onClick={() => runCheck("contradictions")}
              disabled={isBusyElsewhere}
              className="flex items-center justify-center gap-1.5 rounded-lg border border-border bg-surface px-2 py-2 text-xs font-medium text-foreground transition-colors hover:border-border/80 hover:bg-surface-raised disabled:cursor-not-allowed disabled:opacity-50"
            >
              <GitCompare className="h-3.5 w-3.5" />
              Find contradictions
            </button>
          </div>
        )}

        {/* The cost, stated up front. One model call per chunk on the same Ollama
            that answers queries, so this is not a button to press idly. */}
        {!run && (
          <p className="px-0.5 text-[10px] leading-snug text-foreground-muted/70">
            One model pass per chunk, five for contradictions. Minutes on a large source, and
            it shares the model with your chat.
          </p>
        )}

        {result && result.source === source.source && (
          <div className="flex items-start gap-1.5 rounded-md border border-border bg-surface px-2 py-1.5">
            {result.cancelled ? (
              <Ban className="mt-px h-3 w-3 flex-shrink-0 text-foreground-muted" />
            ) : (
              <CheckCircle2 className="mt-px h-3 w-3 flex-shrink-0 text-green-500" />
            )}
            <p className="text-[11px] leading-snug text-foreground">
              {KIND_LABELS[result.kind]}
              {result.cancelled ? " stopped" : " finished"} ·{" "}
              {plural(result.found, KIND_FINDINGS[result.kind])} across {result.checked} of{" "}
              {result.total} chunks
              {result.cancelled && result.checked < result.total && ". The rest were not checked."}
            </p>
          </div>
        )}

        {error && (
          <p className="rounded-md border border-red-500/30 bg-red-500/10 px-2 py-1.5 text-[11px] leading-snug text-foreground">
            {error}
          </p>
        )}
      </div>

      {/* Chunk list */}
      <div className="flex-1 overflow-y-auto">
        {issueCount > 0 && (
          <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
            <span className="text-[10px] uppercase tracking-wide text-foreground-muted/60">
              {plural(chunks.length, "chunk")}
            </span>
            <button
              onClick={() => setOnlyIssues((v) => !v)}
              className={cn(
                "rounded px-1.5 py-0.5 text-[11px] font-medium transition-colors",
                onlyIssues
                  ? "bg-amber-500/15 text-amber-600"
                  : "text-foreground-muted hover:text-foreground"
              )}
            >
              {onlyIssues ? "Showing findings only" : `Show findings only (${issueCount})`}
            </button>
          </div>
        )}

        {isLoading ? (
          <div className="flex items-center justify-center gap-2 py-12 text-foreground-muted">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm">Loading chunks…</span>
          </div>
        ) : loadError ? (
          <div className="px-4 py-8 text-center">
            <p className="mb-1 text-sm text-destructive">Could not load this source</p>
            <p className="text-xs text-foreground-muted">{loadError}</p>
          </div>
        ) : visible.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-foreground-muted">
            {chunks.length === 0 ? "This source has no chunks." : "No findings in this source."}
          </p>
        ) : (
          <div className="space-y-1.5 p-3">
            {visible.map((chunk) => (
              <ChunkRow key={chunk.chunk_index} chunk={chunk} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
