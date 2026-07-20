"use client";

import { useState } from "react";
import { FileText, X, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SourceSummary, IngestionJob } from "@/types";

const CANCELLABLE_STATUSES = new Set(["queued", "ingesting", "building_graph"]);

const PDF_SUFFIXES = new Set([".pdf"]);
const VIDEO_SUFFIXES = new Set([".mp4", ".mov", ".avi", ".mkv", ".webm"]);
const IMAGE_SUFFIXES = new Set([".png", ".jpg", ".jpeg", ".webp", ".tiff"]);

function sourceTypeLabel(suffix: string): string {
  if (suffix === ".url") return "Processing YouTube…";
  if (VIDEO_SUFFIXES.has(suffix)) return "Processing video…";
  if (IMAGE_SUFFIXES.has(suffix)) return "Processing image…";
  if (suffix === ".txt" || suffix === ".md") return "Processing text…";
  return "Processing…";
}

interface ProgressBarProps {
  job: IngestionJob;
}

function ProgressBar({ job }: ProgressBarProps) {
  const { status, pages_done, pages_total, suffix = "" } = job;
  const hasPagesInfo = pages_total != null && pages_total > 0;
  const isPdf = PDF_SUFFIXES.has(suffix);

  if (status === "queued") return null;

  if (status === "ingesting") {
    if (hasPagesInfo) {
      const pct = 10 + (Math.min((pages_done ?? 0) + 1, pages_total!) / pages_total!) * 55;
      return (
        <div className="mt-1.5 space-y-0.5">
          <div className="h-1 w-full rounded-full bg-border overflow-hidden">
            <div
              className="h-full rounded-full bg-blue-500 transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="text-[10px] text-foreground-muted">
            Ingested {(pages_done ?? 0) + 1} of {pages_total} pages
          </p>
        </div>
      );
    }

    // PDF before first page report: pin at 10% with shimmer overlay
    if (isPdf) {
      return (
        <div className="mt-1.5 space-y-0.5">
          <div className="h-1 w-full rounded-full bg-border overflow-hidden">
            <div
              className="h-full rounded-full bg-blue-500 progress-shimmer"
              style={{ width: "10%" }}
            />
          </div>
          <p className="text-[10px] text-foreground-muted">Starting…</p>
        </div>
      );
    }

    // Non-PDF: full-width indeterminate shimmer throughout
    return (
      <div className="mt-1.5 space-y-0.5">
        <div className="h-1 w-full rounded-full bg-border overflow-hidden">
          <div className="h-full w-full rounded-full bg-blue-500 progress-shimmer" />
        </div>
        <p className="text-[10px] text-foreground-muted">{sourceTypeLabel(suffix)}</p>
      </div>
    );
  }

  if (status === "ingested" || status === "building_graph") {
    return (
      <div className="mt-1.5 space-y-0.5">
        <div className="h-1 w-full rounded-full bg-border overflow-hidden">
          <div className="h-full rounded-full bg-green-500" style={{ width: "65%" }} />
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] font-medium text-green-600 dark:text-green-400">
            Ready to use
          </span>
          <span className="text-[10px] text-foreground-muted progress-shimmer rounded-sm px-0.5">
            Building knowledge graph…
          </span>
        </div>
      </div>
    );
  }

  if (status === "done") {
    return (
      <div className="mt-1.5 space-y-0.5">
        <div className="h-1 w-full rounded-full bg-border overflow-hidden">
          <div className="h-full w-full rounded-full bg-green-500" />
        </div>
        <p className="text-[10px] font-medium text-green-600 dark:text-green-400">Done</p>
      </div>
    );
  }

  return null;
}

interface SourceItemProps {
  source: SourceSummary;
  activeJob?: IngestionJob;
  isFading?: boolean;
  onCancelJob: (jobId: string) => void;
}

export function SourceItem({ source, activeJob, isFading = false, onCancelJob }: SourceItemProps) {
  const [showConfirm, setShowConfirm] = useState(false);
  const cancellable = activeJob ? CANCELLABLE_STATUSES.has(activeJob.status) : false;
  const isGraphBuilding = activeJob?.status === "building_graph";

  function handleCancelClick() {
    if (!activeJob) return;
    setShowConfirm(true);
  }

  function handleConfirmCancel() {
    if (!activeJob) return;
    onCancelJob(activeJob.id);
    setShowConfirm(false);
  }

  const confirmMessage = isGraphBuilding
    ? "Source is already usable. Cancelling aborts only the knowledge graph build — the source stays in your library."
    : `Cancel ingestion of '${source.source}'? Progress will be lost and the source will not be available.`;

  const confirmLabel = isGraphBuilding ? "Cancel graph build" : "Cancel ingestion";

  return (
    <div className="group flex flex-col rounded-lg px-3 py-2.5 hover:bg-surface transition-colors">
      <div className="flex items-start gap-2">
        <FileText className="h-4 w-4 text-foreground-muted flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-1">
            <p className="text-xs font-medium text-foreground truncate">{source.source}</p>
            {cancellable && !showConfirm && (
              <button
                onClick={handleCancelClick}
                className={cn(
                  "rounded p-0.5 text-foreground-muted hover:text-destructive flex-shrink-0 transition-opacity",
                  "opacity-0 group-hover:opacity-100"
                )}
                title="Cancel ingestion"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
          <p className="text-[10px] text-foreground-muted">
            {source.chunk_count} chunk{source.chunk_count !== 1 ? "s" : ""}
          </p>
          {activeJob && (
            <div className={cn("transition-opacity duration-1000", isFading && "opacity-0")}>
              <ProgressBar job={activeJob} />
            </div>
          )}
        </div>
      </div>

      {showConfirm && (
        <div className="mt-2 ml-6 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-2">
          <div className="flex items-start gap-1.5 mb-1.5">
            <AlertTriangle className="h-3 w-3 text-amber-500 flex-shrink-0 mt-0.5" />
            <p className="text-[11px] text-foreground leading-snug">{confirmMessage}</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleConfirmCancel}
              className="rounded px-2 py-0.5 text-[11px] font-medium bg-amber-500 text-white hover:bg-amber-600 transition-colors"
            >
              {confirmLabel}
            </button>
            <button
              onClick={() => setShowConfirm(false)}
              className="text-[11px] text-foreground-muted hover:text-foreground transition-colors"
            >
              Keep going
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
