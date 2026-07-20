"use client";

import { useState } from "react";
import { ChevronRight, X, Trash2, Hourglass, AlertTriangle, Loader2, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { DropZone } from "@/components/sources/DropZone";
import type { SourceSummary, IngestionJob } from "@/types";

const CANCELLABLE_STATUSES = new Set(["queued", "ingesting", "building_graph"]);
const VIDEO_SUFFIXES = new Set([".mp4", ".mov", ".avi", ".mkv", ".webm"]);
const IMAGE_SUFFIXES = new Set([".png", ".jpg", ".jpeg", ".webp", ".tiff"]);

function sourceTypeLabel(suffix = ""): string {
  if (suffix === ".url") return "Processing YouTube…";
  if (VIDEO_SUFFIXES.has(suffix)) return "Processing video…";
  if (IMAGE_SUFFIXES.has(suffix)) return "Processing image…";
  if (suffix === ".txt" || suffix === ".md") return "Processing text…";
  return "Processing…";
}

function PendingJobProgress({ job }: { job: IngestionJob }) {
  const { status, pages_done, pages_total, suffix = "" } = job;
  const hasPagesInfo = pages_total != null && pages_total > 0;

  if (status === "queued") {
    return <p className="text-[10px] text-foreground-muted mt-0.5">Waiting to ingest…</p>;
  }

  if (status === "ingesting") {
    if (hasPagesInfo) {
      const pct = 10 + (Math.min((pages_done ?? 0) + 1, pages_total!) / pages_total!) * 55;
      return (
        <div className="space-y-0.5">
          <div className="h-1 w-full rounded-full bg-border overflow-hidden">
            <div
              className="h-full rounded-full bg-blue-500 transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="text-[10px] text-foreground-muted">
            Ingesting… Page {(pages_done ?? 0) + 1} of {pages_total}
          </p>
        </div>
      );
    }
    const isPdf = suffix === ".pdf";
    return (
      <div className="space-y-0.5">
        <div className="h-1 w-full rounded-full bg-border overflow-hidden">
          <div
            className={cn("h-full rounded-full bg-blue-500 progress-shimmer", isPdf ? "" : "w-full")}
            style={isPdf ? { width: "10%" } : undefined}
          />
        </div>
        <p className="text-[10px] text-foreground-muted">
          {isPdf ? "Starting…" : sourceTypeLabel(suffix)}
        </p>
      </div>
    );
  }

  if (status === "ingested") {
    return (
      <div className="space-y-0.5">
        <div className="h-1 w-full rounded-full bg-border overflow-hidden">
          <div className="h-full rounded-full bg-green-500" style={{ width: "65%" }} />
        </div>
        <p className="text-[10px] text-foreground-muted">
          Ready to use — waiting to build knowledge graph…
        </p>
      </div>
    );
  }

  if (status === "building_graph") {
    return (
      <div className="space-y-0.5">
        <div className="h-1 w-full rounded-full bg-border overflow-hidden">
          <div className="h-full rounded-full bg-green-500 progress-shimmer" style={{ width: "65%" }} />
        </div>
        <p className="text-[10px] text-foreground-muted">Building knowledge graph…</p>
      </div>
    );
  }

  if (status === "done") {
    return (
      <div className="space-y-0.5">
        <div className="h-1 w-full rounded-full bg-border overflow-hidden">
          <div className="h-full w-full rounded-full bg-green-500" />
        </div>
        <p className="text-[10px] font-medium text-green-600 dark:text-green-400">Done</p>
      </div>
    );
  }

  if (status === "cancelled") {
    return <p className="text-[10px] text-foreground-muted">Cancelled</p>;
  }

  if (status.startsWith("error")) {
    return <p className="text-[10px] text-red-500 truncate">{status}</p>;
  }

  return null;
}

interface SourcesPanelProps {
  sources: SourceSummary[];
  jobs: IngestionJob[];
  isUploading: boolean;
  isCollapsed: boolean;
  clearableJobCount: number;
  fadingJobIds: Set<string>;
  hiddenJobIds: Set<string>;
  onToggleCollapse: () => void;
  onDropFiles: (files: File[]) => void;
  onCancelJob: (jobId: string) => void;
  onClearCompleted: () => void;
}

export function SourcesPanel({
  sources,
  jobs,
  isUploading,
  isCollapsed,
  clearableJobCount,
  fadingJobIds,
  hiddenJobIds,
  onToggleCollapse,
  onDropFiles,
  onCancelJob,
  onClearCompleted,
}: SourcesPanelProps) {
  const [pendingCancelId, setPendingCancelId] = useState<string | null>(null);

  // Jobs not yet in the sources list — includes done jobs until they're hidden
  // so there's no gap between "done" and the source appearing in SourceItem.
  const pendingJobs = jobs.filter(
    (j) => j.source && !sources.find((s) => s.source === j.source) && !hiddenJobIds.has(j.id)
  );

  function handleCancelConfirm(jobId: string) {
    onCancelJob(jobId);
    setPendingCancelId(null);
  }

  return (
    <aside
      className={cn(
        "flex flex-col border-l border-border bg-surface transition-all duration-200 flex-shrink-0",
        isCollapsed ? "w-0 overflow-hidden border-l-0" : "w-72"
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-3 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-1">
          <button
            onClick={onToggleCollapse}
            className="rounded p-1 text-foreground-muted hover:text-foreground transition-colors"
            title="Collapse panel"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
          <span className="text-sm font-semibold text-foreground ml-0.5">Ingest</span>
        </div>
        {clearableJobCount > 0 && (
          <button
            onClick={onClearCompleted}
            className="rounded p-1 text-foreground-muted hover:text-foreground transition-colors"
            title={`Clear ${clearableJobCount} finished job${clearableJobCount !== 1 ? "s" : ""} from display`}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* Active-job queue — completed sources live in the Sources modal only */}
      <div className="flex-1 overflow-y-auto py-1">
        {pendingJobs.length > 0 && pendingJobs.map((job) => {
              const isConfirming = pendingCancelId === job.id;
              const isFading = fadingJobIds.has(job.id);
              const jobIcon =
                job.status === "queued" ? (
                  <Hourglass className="h-4 w-4 text-yellow-500 dark:text-yellow-400 flex-shrink-0 mt-0.5" />
                ) : job.status === "done" || job.status === "ingested" ? (
                  <CheckCircle2 className="h-4 w-4 text-green-500 flex-shrink-0 mt-0.5" />
                ) : (
                  <Loader2 className="h-4 w-4 text-foreground-muted flex-shrink-0 mt-0.5 animate-spin" />
                );
              return (
                <div key={job.id} className={cn("px-3 py-2.5 transition-opacity duration-1000", isFading && "opacity-0")}>
                  <div className="flex items-start gap-2">
                    {jobIcon}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-1">
                        <p className="text-xs font-medium text-foreground truncate">{job.source}</p>
                        {CANCELLABLE_STATUSES.has(job.status) && !isConfirming && (
                          <button
                            onClick={() => setPendingCancelId(job.id)}
                            className="rounded p-0.5 text-foreground-muted hover:text-destructive flex-shrink-0"
                            title="Cancel ingestion"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        )}
                      </div>
                      <PendingJobProgress job={job} />
                    </div>
                  </div>
                  {isConfirming && (
                    <div className="mt-2 ml-6 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-2">
                      <div className="flex items-start gap-1.5 mb-1.5">
                        <AlertTriangle className="h-3 w-3 text-amber-500 flex-shrink-0 mt-0.5" />
                        <p className="text-[11px] text-foreground leading-snug">
                          Cancel ingestion of &lsquo;{job.source}&rsquo;? Progress will be lost.
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleCancelConfirm(job.id)}
                          className="rounded px-2 py-0.5 text-[11px] font-medium bg-amber-500 text-white hover:bg-amber-600 transition-colors"
                        >
                          Cancel ingestion
                        </button>
                        <button
                          onClick={() => setPendingCancelId(null)}
                          className="text-[11px] text-foreground-muted hover:text-foreground transition-colors"
                        >
                          Keep going
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
      </div>

      {/* Drop zone */}
      <div className="border-t border-border pt-2">
        <DropZone onDrop={onDropFiles} isUploading={isUploading} />
      </div>
    </aside>
  );
}

// Collapsed toggle button shown when panel is hidden
export function SourcesPanelToggle({
  onClick,
  activeJobCount,
}: {
  onClick: () => void;
  activeJobCount: number;
}) {
  return (
    <button
      onClick={onClick}
      className="fixed right-4 top-1/2 -translate-y-1/2 flex flex-col items-center gap-1 rounded-l-lg border border-r-0 border-border bg-surface px-2 py-3 text-foreground-muted hover:text-foreground transition-colors shadow-sm"
      title="Show sources"
    >
      <ChevronRight className="h-4 w-4 rotate-180" />
      {activeJobCount > 0 && <span className="h-2 w-2 rounded-full bg-blue-500" />}
    </button>
  );
}
