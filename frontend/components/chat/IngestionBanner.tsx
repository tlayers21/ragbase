"use client";

import { AlertTriangle } from "lucide-react";
import { humanizeSourceName } from "@/lib/utils";
import type { IngestionJob } from "@/types";

/** How many source names to spell out before collapsing the rest into "+N more". */
const MAX_NAMED_SOURCES = 2;

/**
 * Describes what the queue is doing in the user's words.
 *
 * Extraction and graph building are wildly different in feel — one is a few
 * seconds of parsing, the other is an LLM call per chunk that runs for minutes —
 * so naming the phase is what makes the slowdown make sense rather than look
 * like a bug.
 */
function phaseLabel(jobs: IngestionJob[]): string {
  const extracting = jobs.some((j) => j.status === "queued" || j.status === "ingesting");
  const graphing = jobs.some((j) => j.status === "building_graph");
  if (extracting && graphing) return "Extracting text and building knowledge graphs";
  if (graphing) return "Building the knowledge graph";
  return "Extracting and embedding text";
}

function sourceList(jobs: IngestionJob[]): string {
  const names = jobs.map((j) => humanizeSourceName(j.source));
  if (names.length <= MAX_NAMED_SOURCES) return names.join(", ");
  const shown = names.slice(0, MAX_NAMED_SOURCES).join(", ");
  return `${shown} +${names.length - MAX_NAMED_SOURCES} more`;
}

interface IngestionBannerProps {
  /** Jobs in a status that actually consumes the machine — see useIngestion. */
  jobs: IngestionJob[];
}

/**
 * Unmissable bar shown while anything is ingesting.
 *
 * Ingestion and queries share one local Ollama process on one GPU, so a query
 * asked mid-ingest is several times slower than the same query asked when the
 * machine is idle. Without this the app looks broken rather than busy, and the
 * only other signal — the ingest panel on the right — is collapsible and easy to
 * miss. Deliberately has **no dismiss control**: it disappears when the queue
 * drains and not a moment earlier, because the condition it reports is still
 * true regardless of whether the user has acknowledged it.
 */
export function IngestionBanner({ jobs }: IngestionBannerProps) {
  if (jobs.length === 0) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex-shrink-0 flex items-center gap-3 border-b-2 border-warning-border bg-warning px-4 py-2.5 text-warning-foreground"
    >
      <AlertTriangle className="h-5 w-5 flex-shrink-0" strokeWidth={2.5} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-bold leading-tight">
          Ingestion in progress — responses will be slow
        </p>
        <p className="truncate text-xs font-medium leading-tight opacity-90">
          {phaseLabel(jobs)} · {sourceList(jobs)}
        </p>
      </div>
      <span className="flex-shrink-0 rounded-full border border-warning-foreground/30 px-2 py-0.5 text-xs font-bold tabular-nums">
        {jobs.length} {jobs.length === 1 ? "job" : "jobs"}
      </span>
    </div>
  );
}
