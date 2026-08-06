"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import dynamic from "next/dynamic";
import { X, Search, Trash2, FileText, Loader2, ChevronLeft } from "lucide-react";
import { fetchSources, deleteSource as apiDeleteSource, cancelIngestion, getSourceFileUrl, fetchSourceText } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { SourceSummary } from "@/types";

// Lazy-load react-pdf to keep the main bundle light (PDF.js is large)
const PDFPreview = dynamic(() => import("@/components/sources/PDFPreview"), { ssr: false });
const PDFThumbnailView = dynamic(() => import("@/components/sources/PDFThumbnail"), { ssr: false });

// ── Helpers ───────────────────────────────────────────────────────────────────

type SourceType = "pdf" | "image" | "text";

// ── Thumbnail ─────────────────────────────────────────────────────────────────

type ThumbnailState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "pdf" }
  | { status: "image" }
  | { status: "text"; content: string }
  | { status: "none" };

function SourceThumbnail({ source }: { source: string }) {
  const [state, setState] = useState<ThumbnailState>({ status: "idle" });
  const containerRef = useRef<HTMLDivElement>(null);
  const fileUrl = getSourceFileUrl(source);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        observer.disconnect();
        setState({ status: "loading" });

        fetch(fileUrl, { method: "HEAD" })
          .then((r) => {
            if (!r.ok) { setState({ status: "none" }); return; }
            const ct = r.headers.get("content-type") ?? "";
            if (ct.includes("pdf")) {
              setState({ status: "pdf" });
            } else if (ct.startsWith("image/")) {
              setState({ status: "image" });
            } else {
              fetchSourceText(source).then((text) => {
                setState({ status: "text", content: text.slice(0, 300) });
              }).catch(() => setState({ status: "none" }));
            }
          })
          .catch(() => setState({ status: "none" }));
      },
      { rootMargin: "50px" }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [fileUrl, source]);

  return (
    <div
      ref={containerRef}
      className="w-full h-24 rounded-md overflow-hidden bg-surface-raised mb-2 flex items-center justify-center"
    >
      {(state.status === "idle" || state.status === "loading") && (
        <div className="h-3 w-3 rounded-full bg-border animate-pulse" />
      )}
      {state.status === "pdf" && (
        <div className="w-full h-full flex items-center justify-center overflow-hidden">
          <PDFThumbnailView url={fileUrl} />
        </div>
      )}
      {state.status === "image" && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={fileUrl} alt="" className="w-full h-full object-cover" />
      )}
      {state.status === "text" && (
        <div className="relative w-full h-full overflow-hidden">
          <p className="text-[8px] text-foreground-muted font-mono p-1.5 leading-tight whitespace-pre-wrap">
            {state.content}
          </p>
          <div className="absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-surface-raised to-transparent" />
        </div>
      )}
      {state.status === "none" && (
        <FileText className="h-6 w-6 text-foreground-muted/30" />
      )}
    </div>
  );
}

// ── Preview pane ──────────────────────────────────────────────────────────────

interface PreviewPaneProps {
  source: SourceSummary;
  onClose: () => void;
}

function PreviewPane({ source, onClose }: PreviewPaneProps) {
  const [type, setType] = useState<SourceType | null>(null);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fileUrl = getSourceFileUrl(source.source);

  useEffect(() => {
    setIsLoading(true);
    setError(null);
    setType(null);
    setTextContent(null);

    // HEAD the file to detect Content-Type
    fetch(fileUrl, { method: "HEAD" })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        const ct = r.headers.get("content-type") ?? "";
        if (ct.includes("pdf")) return "pdf" as SourceType;
        if (ct.startsWith("image/")) return "image" as SourceType;
        return "text" as SourceType;
      })
      .then(async (detectedType) => {
        setType(detectedType);
        if (detectedType === "text") {
          const text = await fetchSourceText(source.source);
          setTextContent(text);
        }
        setIsLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setIsLoading(false);
      });
  }, [source.source, fileUrl]);

  return (
    <div className="flex flex-col h-full">
      {/* Preview header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border flex-shrink-0">
        <button
          onClick={onClose}
          className="rounded p-1 text-foreground-muted hover:text-foreground transition-colors"
          title="Back to sources"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <FileText className="h-4 w-4 text-foreground-muted flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-foreground truncate">{source.source}</p>
          <p className="text-[11px] text-foreground-muted">
            {source.chunk_count} chunk{source.chunk_count !== 1 ? "s" : ""}
          </p>
        </div>
      </div>

      {/* Preview content */}
      <div className="flex-1 overflow-auto">
        {isLoading && (
          <div className="flex items-center justify-center gap-2 py-12 text-foreground-muted">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm">Loading preview…</span>
          </div>
        )}

        {!isLoading && error && (
          <div className="px-4 py-8 text-center">
            <p className="text-sm text-destructive mb-1">Preview unavailable</p>
            <p className="text-xs text-foreground-muted">{error}</p>
          </div>
        )}

        {!isLoading && !error && type === "pdf" && (
          <PDFPreview url={fileUrl} />
        )}

        {!isLoading && !error && type === "image" && (
          <div className="flex items-center justify-center p-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={fileUrl}
              alt={source.source}
              className="max-w-full max-h-[60vh] rounded-lg object-contain"
            />
          </div>
        )}

        {!isLoading && !error && type === "text" && (
          <div className="relative p-4">
            <pre className="text-xs text-foreground leading-relaxed whitespace-pre-wrap font-mono">
              {(textContent ?? "").slice(0, 800)}
            </pre>
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-background to-transparent" />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Source card ───────────────────────────────────────────────────────────────

interface SourceCardProps {
  source: SourceSummary;
  isConfirming: boolean;
  isBuildingGraph?: boolean;
  onPreview: (source: SourceSummary) => void;
  onRequestDelete: (source: string) => void;
  onConfirmDelete: (source: string) => void;
  onCancelConfirm: () => void;
}

function SourceCard({
  source,
  isConfirming,
  isBuildingGraph,
  onPreview,
  onRequestDelete,
  onConfirmDelete,
  onCancelConfirm,
}: SourceCardProps) {
  return (
    <div
      className={cn(
        "group relative flex flex-col gap-2 rounded-lg border border-border bg-surface p-3 transition-colors cursor-pointer",
        isConfirming
          ? "border-red-500/40 bg-red-500/5"
          : "hover:border-border/80 hover:bg-surface-raised"
      )}
      onClick={() => !isConfirming && onPreview(source)}
    >
      <div className="flex items-start justify-between gap-2">
        <FileText className="h-5 w-5 text-foreground-muted flex-shrink-0 mt-0.5" />
        {isConfirming ? (
          <div className="flex items-center gap-1 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => onConfirmDelete(source.source)}
              className="rounded px-1.5 py-0.5 text-[11px] font-medium bg-red-500 text-white hover:bg-red-600 transition-colors"
            >
              Delete
            </button>
            <button
              onClick={onCancelConfirm}
              className="rounded px-1.5 py-0.5 text-[11px] font-medium text-foreground-muted hover:text-foreground transition-colors"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={(e) => { e.stopPropagation(); onRequestDelete(source.source); }}
            className="opacity-0 group-hover:opacity-100 rounded p-0.5 text-foreground-muted hover:text-destructive transition-all"
            title="Delete source"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {isConfirming && (
        <p className="text-[11px] text-red-600 dark:text-red-400 leading-snug" onClick={(e) => e.stopPropagation()}>
          {isBuildingGraph
            ? <>Still building knowledge graph. Cancel build and delete &lsquo;{source.source}&rsquo;?</>
            : <>Delete &lsquo;{source.source}&rsquo;? This cannot be undone.</>}
        </p>
      )}

      {!isConfirming && <SourceThumbnail source={source.source} />}

      <div className="min-w-0">
        <p className="text-xs font-medium text-foreground truncate" title={source.source}>
          {source.source}
        </p>
        <p className="mt-0.5 text-[11px] text-foreground-muted">
          {source.chunk_count} chunk{source.chunk_count !== 1 ? "s" : ""}
          {source.flagged_count > 0 && (
            <span className="ml-2 text-amber-500">{source.flagged_count} flagged</span>
          )}
        </p>
      </div>
    </div>
  );
}

// ── Modal ─────────────────────────────────────────────────────────────────────

interface SourcesModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSourcesChanged?: () => void;
  buildingGraphJobBySrc?: Record<string, string>;
}

export function SourcesModal({ isOpen, onClose, onSourcesChanged, buildingGraphJobBySrc }: SourcesModalProps) {
  const [sources, setSources] = useState<SourceSummary[]>([]);
  const [isLoadingSources, setIsLoadingSources] = useState(false);
  const [query, setQuery] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [preview, setPreview] = useState<SourceSummary | null>(null);

  // Fetch fresh data every time the modal opens
  useEffect(() => {
    if (!isOpen) return;
    setIsLoadingSources(true);
    setPreview(null);
    setConfirming(null);
    fetchSources()
      .then(setSources)
      .catch(() => setSources([]))
      .finally(() => setIsLoadingSources(false));
  }, [isOpen]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? sources.filter((s) => s.source.toLowerCase().includes(q)) : sources;
  }, [sources, query]);

  const handleRequestDelete = useCallback((source: string) => {
    setConfirming(source);
  }, []);

  const handleConfirmDelete = useCallback(
    async (source: string) => {
      try {
        const jobId = buildingGraphJobBySrc?.[source];
        if (jobId) {
          await cancelIngestion(jobId);
        }
        await apiDeleteSource(source);
        setSources((prev) => prev.filter((s) => s.source !== source));
        setConfirming(null);
        onSourcesChanged?.();
      } catch {
        // keep confirming state so user can retry
      }
    },
    [onSourcesChanged, buildingGraphJobBySrc]
  );

  const handleClose = useCallback(() => {
    setConfirming(null);
    setQuery("");
    setPreview(null);
    onClose();
  }, [onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      onClick={(e) => e.target === e.currentTarget && handleClose()}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={handleClose} />

      {/* Panel */}
      <div className="relative z-10 w-full max-w-xl mx-4 rounded-xl border border-border bg-background shadow-2xl flex flex-col max-h-[80vh]">
        {preview ? (
          // ── Preview mode ──────────────────────────────────────────────────
          <>
            <div className="flex items-center justify-between px-4 py-3 border-b border-border flex-shrink-0">
              <h2 className="text-sm font-semibold text-foreground">Preview</h2>
              <button
                onClick={handleClose}
                className="rounded p-1 text-foreground-muted hover:text-foreground transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="flex-1 overflow-hidden">
              <PreviewPane source={preview} onClose={() => setPreview(null)} />
            </div>
          </>
        ) : (
          // ── Grid mode ─────────────────────────────────────────────────────
          <>
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-border flex-shrink-0">
              <h2 className="text-sm font-semibold text-foreground">
                Sources
                {!isLoadingSources && (
                  <span className="ml-2 text-xs font-normal text-foreground-muted">
                    {sources.length} total
                  </span>
                )}
              </h2>
              <button
                onClick={handleClose}
                className="rounded p-1 text-foreground-muted hover:text-foreground transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Search */}
            <div className="px-4 py-2 border-b border-border flex-shrink-0">
              <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-1.5">
                <Search className="h-3.5 w-3.5 text-foreground-muted flex-shrink-0" />
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Filter sources…"
                  className="flex-1 bg-transparent text-sm text-foreground placeholder:text-foreground-muted outline-none"
                  autoFocus
                />
                {query && (
                  <button
                    onClick={() => setQuery("")}
                    className="text-foreground-muted hover:text-foreground"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto">
              {isLoadingSources ? (
                <div className="flex items-center justify-center gap-2 py-12 text-foreground-muted">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span className="text-sm">Loading sources…</span>
                </div>
              ) : filtered.length === 0 ? (
                <p className="px-4 py-8 text-center text-sm text-foreground-muted">
                  {query ? "No sources match your filter." : "No sources ingested yet."}
                </p>
              ) : (
                <div className="grid grid-cols-2 gap-2 p-3">
                  {filtered.map((source) => (
                    <SourceCard
                      key={source.source}
                      source={source}
                      isConfirming={confirming === source.source}
                      isBuildingGraph={!!buildingGraphJobBySrc?.[source.source]}
                      onPreview={setPreview}
                      onRequestDelete={handleRequestDelete}
                      onConfirmDelete={handleConfirmDelete}
                      onCancelConfirm={() => setConfirming(null)}
                    />
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
