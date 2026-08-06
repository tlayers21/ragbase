"use client";

import { useState, useEffect } from "react";
import { ChevronRight, X, Trash2, Hourglass, AlertTriangle, Loader2, CheckCircle2, GitBranch } from "lucide-react";
import { cn } from "@/lib/utils";
import { DropZone } from "@/components/sources/DropZone";
import { generateTitle } from "@/lib/api";
import type { IngestionJob } from "@/types";

// Once a source reaches "ingested" it's already queryable — the graph-build
// stages (waiting_for_graph, building_graph) that follow are non-destructive
// background work, so cancelling them wouldn't undo anything worth undoing.
const CANCELLABLE_STATUSES = new Set(["queued", "ingesting"]);
const VIDEO_SUFFIXES = new Set([".mp4", ".mov", ".avi", ".mkv", ".webm"]);
const IMAGE_SUFFIXES = new Set([".png", ".jpg", ".jpeg", ".webp", ".tiff"]);

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s]/g, "")
    .trim()
    .replace(/\s+/g, "_")
    .slice(0, 100);
}

function PendingJobProgress({ job }: { job: IngestionJob }) {
  const { status, estimated_seconds, suffix = "" } = job;
  const [barPct, setBarPct] = useState(10);
  const [overEstimate, setOverEstimate] = useState(false);

  useEffect(() => {
    if (status !== "ingesting") {
      setBarPct(10);
      setOverEstimate(false);
      return;
    }

    const estMs = (estimated_seconds ?? 0) * 1000;
    if (!estMs) return;

    const startTime = performance.now();
    let rafId: number;

    const tick = (now: number) => {
      const elapsed = now - startTime;
      const t = Math.min(1, elapsed / estMs);
      const eased = 1 - Math.pow(1 - t, 2.5);
      setBarPct(10 + eased * 52);
      setOverEstimate(elapsed > estMs);
      if (elapsed < estMs) {
        rafId = requestAnimationFrame(tick);
      }
    };

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [status, estimated_seconds]);

  if (status === "queued") {
    return <p className="text-[10px] text-foreground-muted mt-0.5">Waiting to ingest…</p>;
  }

  if (status === "ingesting") {
    const shimmer = overEstimate || !estimated_seconds;
    const label =
      suffix === ".url" ? "Processing YouTube…"
      : VIDEO_SUFFIXES.has(suffix) ? "Processing video…"
      : IMAGE_SUFFIXES.has(suffix) ? "Processing image…"
      : suffix === ".txt" || suffix === ".md" ? "Processing text…"
      : "Processing PDF…";
    return (
      <div className="space-y-0.5">
        <div className="h-1 w-full rounded-full bg-border overflow-hidden">
          <div
            className={cn("h-full rounded-full bg-blue-500", shimmer && "progress-shimmer")}
            style={{ width: `${barPct}%` }}
          />
        </div>
        <p className="text-[10px] text-foreground-muted">{label}</p>
      </div>
    );
  }

  if (status === "ingested") {
    return (
      <div className="space-y-1">
        <div className="h-1 w-full rounded-full bg-border overflow-hidden">
          <div className="h-full rounded-full bg-green-500" style={{ width: "65%" }} />
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[9px] font-medium text-green-600 dark:text-green-400 bg-green-500/10 rounded-full px-1.5 py-0.5">
            Ready
          </span>
          <p className="text-[10px] text-foreground-muted">Preparing knowledge graph…</p>
        </div>
      </div>
    );
  }

  if (status === "waiting_for_graph") {
    return (
      <div className="space-y-1">
        <div className="h-1 w-full rounded-full bg-border overflow-hidden">
          <div className="h-full rounded-full bg-green-500" style={{ width: "65%" }} />
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[9px] font-medium text-green-600 dark:text-green-400 bg-green-500/10 rounded-full px-1.5 py-0.5">
            Ready
          </span>
          <Hourglass className="h-3 w-3 text-foreground-muted/60 flex-shrink-0" />
          <p className="text-[10px] text-foreground-muted">Waiting to build knowledge graph…</p>
        </div>
      </div>
    );
  }

  if (status === "building_graph") {
    return (
      <div className="space-y-1">
        <div className="h-1 w-full rounded-full bg-border overflow-hidden">
          <div className="h-full rounded-full bg-green-500 progress-shimmer" style={{ width: "65%" }} />
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[9px] font-medium text-green-600 dark:text-green-400 bg-green-500/10 rounded-full px-1.5 py-0.5">
            Ready
          </span>
          <Loader2 className="h-3 w-3 text-foreground-muted/60 animate-spin flex-shrink-0" />
          <p className="text-[10px] text-foreground-muted">Building knowledge graph…</p>
        </div>
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

function TextIngestForm({
  onIngest,
}: {
  onIngest: (text: string, sourceName: string) => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<"idle" | "generating" | "ingesting">("idle");

  async function handleSubmit() {
    setError(null);
    if (!text.trim()) { setError("Text cannot be empty"); return; }

    setPhase("generating");
    let sourceName: string;
    try {
      const title = await generateTitle(text.trim());
      const slug = title ? slugify(title) : "";
      sourceName = slug || `text_${Date.now()}`;
    } catch {
      sourceName = `text_${Date.now()}`;
    }

    setPhase("ingesting");
    try {
      await onIngest(text.trim(), sourceName);
      setText("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ingest failed");
    } finally {
      setPhase("idle");
    }
  }

  const loading = phase !== "idle";
  const buttonLabel =
    phase === "generating" ? "Generating title…" :
    phase === "ingesting" ? "Ingesting…" :
    "Ingest text";

  return (
    <div className="p-3 space-y-2">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Paste or type text to ingest…"
        className="w-full h-24 rounded-lg border border-border bg-background px-2.5 py-2 text-xs text-foreground placeholder:text-foreground-muted/50 resize-none focus:outline-none focus:ring-1 focus:ring-primary/50"
      />
      {error && <p className="text-[10px] text-red-500">{error}</p>}
      <button
        onClick={handleSubmit}
        disabled={loading}
        className="w-full rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
      >
        {buttonLabel}
      </button>
    </div>
  );
}

function YouTubeIngestForm({
  onIngest,
}: {
  onIngest: (url: string) => Promise<void>;
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function isYouTubeUrl(urlStr: string): boolean {
    try {
      const parsed = new URL(urlStr);
      return parsed.hostname.includes("youtube.com") || parsed.hostname.includes("youtu.be");
    } catch {
      return false;
    }
  }

  async function handleSubmit() {
    setError(null);
    const trimmedUrl = url.trim();
    if (!trimmedUrl) { setError("URL is required"); return; }
    try { new URL(trimmedUrl); } catch { setError("Please enter a valid YouTube URL"); return; }
    if (!isYouTubeUrl(trimmedUrl)) {
      setError("Please enter a valid YouTube URL");
      return;
    }
    setLoading(true);
    try {
      await onIngest(trimmedUrl);
      setUrl("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ingest failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-3 space-y-2">
      <input
        type="url"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="Paste a YouTube video URL"
        className="w-full rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs text-foreground placeholder:text-foreground-muted/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
      />
      <p className="text-[10px] text-foreground-muted/60">Only YouTube URLs are currently supported</p>
      {error && <p className="text-[10px] text-red-500">{error}</p>}
      <button
        onClick={handleSubmit}
        disabled={loading}
        className="w-full rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
      >
        {loading ? "Fetching video info…" : "Ingest YouTube video"}
      </button>
    </div>
  );
}

type IngestTab = "file" | "text" | "url";

interface SourcesPanelProps {
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
  onIngestText: (text: string, sourceName: string) => Promise<void>;
  onIngestUrl: (url: string) => Promise<void>;
}

export function SourcesPanel({
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
  onIngestText,
  onIngestUrl,
}: SourcesPanelProps) {
  const [pendingCancelId, setPendingCancelId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<IngestTab>("file");

  // Show all non-hidden jobs; active-state jobs always visible regardless of sources list
  const pendingJobs = jobs.filter((j) => !hiddenJobIds.has(j.id));

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
        {pendingJobs.length > 0 &&
          pendingJobs.map((job) => {
            const isConfirming = pendingCancelId === job.id;
            const isFading = fadingJobIds.has(job.id);
            const jobIcon =
              job.status === "queued" ? (
                <Hourglass className="h-4 w-4 text-yellow-500 dark:text-yellow-400 flex-shrink-0 mt-0.5" />
              ) : job.status === "done" || job.status === "ingested" ? (
                <CheckCircle2 className="h-4 w-4 text-green-500 flex-shrink-0 mt-0.5" />
              ) : job.status === "waiting_for_graph" ? (
                <Hourglass className="h-4 w-4 text-foreground-muted/60 flex-shrink-0 mt-0.5" />
              ) : job.status === "building_graph" ? (
                <GitBranch className="h-4 w-4 text-green-500 flex-shrink-0 mt-0.5" />
              ) : (
                <Loader2 className="h-4 w-4 text-foreground-muted flex-shrink-0 mt-0.5 animate-spin" />
              );
            return (
              <div
                key={job.id}
                className={cn(
                  "px-3 py-2.5 transition-opacity duration-1000",
                  isFading && "opacity-0"
                )}
              >
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

      {/* Ingest tabs */}
      <div className="border-t border-border flex-shrink-0">
        <div className="flex border-b border-border">
          {(["file", "text", "url"] as IngestTab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "flex-1 py-2 text-[11px] font-medium transition-colors",
                activeTab === tab
                  ? "text-foreground border-b-2 border-primary"
                  : "text-foreground-muted hover:text-foreground"
              )}
            >
              {tab === "url" ? "YouTube" : tab === "text" ? "Text" : "File"}
            </button>
          ))}
        </div>
        {activeTab === "file" && <DropZone onDrop={onDropFiles} isUploading={isUploading} />}
        {activeTab === "text" && <TextIngestForm onIngest={onIngestText} />}
        {activeTab === "url" && <YouTubeIngestForm onIngest={onIngestUrl} />}
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
