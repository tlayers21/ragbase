"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import dynamic from "next/dynamic";
import {
  X,
  Search,
  Trash2,
  FileText,
  Loader2,
  ChevronLeft,
  Hourglass,
  GitBranch,
} from "lucide-react";
import {
  fetchSources,
  deleteSource as apiDeleteSource,
  getSourceFileUrl,
  getStaticSourceFileUrl,
  fetchTextFile,
  fetchSourceType,
} from "@/lib/api";
import { cn, sourceTypeFromExt } from "@/lib/utils";
import { isActiveStatus } from "@/hooks/useIngestion";
import type { IngestionJob, SourceSummary } from "@/types";

// Lazy-load react-pdf to keep the main bundle light (PDF.js is large)
const PDFPreview = dynamic(() => import("@/components/sources/PDFPreview"), { ssr: false });
const PDFThumbnailView = dynamic(() => import("@/components/sources/PDFThumbnail"), { ssr: false });

// -- Helpers -------------------------------------------------------------------

// "binary" covers everything the ingest surface accepts but nothing here can
// render - the office formats, e-books and video. It is a real preview outcome,
// not a failure: see sourceTypeFromExt in lib/utils.ts.
type SourceType = "pdf" | "image" | "text" | "binary";

/**
 * Where to load a source's stored file from.
 *
 * Prefers the same-origin Next.js static mount so previews and PDF rendering
 * never touch the FastAPI server - it has queries to answer, and these are whole
 * multi-hundred-MB files. Falls back to `/sources/{source}/file` when the user id
 * can't be read, and returns null when there is no stored original at all.
 */
function useSourceFileUrl(source: SourceSummary): string | null {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    // Cleared up front, not just on the no-file branch. Without this the hook
    // kept returning the *previous* source's URL until the async resolve landed,
    // so opening a second preview briefly rendered the first file.
    setUrl(null);

    // `GET /documents/` derives file_ext from a listing of data/sources, so an
    // empty one means no original was ever stored - the FastAPI fallback would
    // 404 by construction. YouTube is the ordinary case here: its transcript
    // comes straight out of Whisper and is never written to disk.
    if (!source.file_ext) return;

    let cancelled = false;
    getStaticSourceFileUrl(source.source, source.file_ext).then((staticUrl) => {
      if (!cancelled) setUrl(staticUrl ?? getSourceFileUrl(source.source));
    });
    return () => {
      cancelled = true;
    };
  }, [source.source, source.file_ext]);

  return url;
}

/** Type from the extension when we have it; otherwise HEAD the API as before. */
async function resolveSourceType(
  source: SourceSummary,
  signal: AbortSignal
): Promise<SourceType> {
  if (source.file_ext) return sourceTypeFromExt(source.file_ext);
  return fetchSourceType(source.source, signal);
}

// -- Thumbnail -----------------------------------------------------------------

type ThumbnailState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "pdf" }
  | { status: "image" }
  | { status: "text"; content: string }
  | { status: "none" };

function SourceThumbnail({ source }: { source: SourceSummary }) {
  const [state, setState] = useState<ThumbnailState>({ status: "idle" });
  const containerRef = useRef<HTMLDivElement>(null);
  const fileUrl = useSourceFileUrl(source);

  // Where a previewable original doesn't exist, fall back to the opening of the
  // source's first chunk, which GET /documents/ carries for exactly this. A
  // YouTube transcript never has a file on disk and an office document's bytes are
  // a ZIP header, so both used to render an empty box with a generic icon while
  // their ingested text sat in ChromaDB. Only when there is no preview either does
  // it settle on the icon.
  const noFileState = useCallback(
    (): ThumbnailState =>
      source.preview ? { status: "text", content: source.preview } : { status: "none" },
    [source.preview]
  );

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    // No stored original - the chunk preview is already in hand, so there is
    // nothing to fetch and no reason to wait for the card to scroll into view.
    if (!source.file_ext) {
      setState(noFileState());
      return;
    }
    if (!fileUrl) return;

    // Aborted on unmount. The card grid unmounts the instant a preview opens, and
    // a request left in flight then fails as net::ERR_FAILED - which Chrome
    // surfaces as a misleading CORS error and which raced the preview's own request.
    const controller = new AbortController();

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        observer.disconnect();
        setState({ status: "loading" });

        resolveSourceType(source, controller.signal)
          .then(async (type) => {
            // "binary" settles on the generic icon. It must not fall through to
            // the text branch: that fetches the whole file to slice 300
            // characters off it, which for a .mp4 source meant downloading the
            // entire video to render a thumbnail of its header bytes.
            if (type === "binary") {
              setState(noFileState());
              return;
            }
            if (type !== "text") {
              setState({ status: type });
              return;
            }
            const text = await fetchTextFile(fileUrl, controller.signal);
            setState({ status: "text", content: text.slice(0, 300) });
          })
          .catch((err: Error) => {
            if (err.name !== "AbortError") setState(noFileState());
          });
      },
      { rootMargin: "50px" }
    );
    observer.observe(el);
    return () => {
      observer.disconnect();
      controller.abort();
    };
  }, [fileUrl, source, noFileState]);

  return (
    <div
      ref={containerRef}
      className="w-full h-24 rounded-md overflow-hidden bg-surface-raised mb-2 flex items-center justify-center"
    >
      {(state.status === "idle" || state.status === "loading") && (
        <div className="h-3 w-3 rounded-full bg-border animate-pulse" />
      )}
      {state.status === "pdf" && fileUrl && (
        <div className="w-full h-full flex items-center justify-center overflow-hidden">
          <PDFThumbnailView url={fileUrl} />
        </div>
      )}
      {state.status === "image" && fileUrl && (
        // crossOrigin makes this a CORS request like any fetch() of the same URL,
        // so both share one cache entry - see the Vary: Origin note in
        // api/sources.py. Harmless on the same-origin static URL, and still
        // required on the FastAPI fallback.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={fileUrl} alt="" crossOrigin="anonymous" className="w-full h-full object-cover" />
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

// -- Preview pane --------------------------------------------------------------

/**
 * The two cases with no renderable original: a source that was never written to
 * disk (YouTube) and one whose bytes aren't viewable (office formats, video).
 *
 * Both still have ingested text, so they show the opening of the first chunk
 * rather than an empty panel. The reason there's no original stays as a caption -
 * "no file was stored" and "the file has no text in it" are different facts, and
 * collapsing them would make a failed extraction look like a healthy source.
 */
function NoFilePreview({ source, message }: { source: SourceSummary; message: string }) {
  const indexed = `Indexed as ${source.chunk_count} chunk${source.chunk_count !== 1 ? "s" : ""}.`;

  if (!source.preview) {
    return (
      <div className="px-4 py-10 text-center">
        <FileText className="mx-auto mb-2 h-6 w-6 text-foreground-muted/30" />
        <p className="text-sm text-foreground-muted">{message}</p>
        <p className="mt-1 text-xs text-foreground-muted/70">{indexed}</p>
      </div>
    );
  }

  return (
    <div className="p-4">
      <p className="mb-2 flex items-center gap-1.5 text-xs text-foreground-muted/70">
        <FileText className="h-3 w-3" />
        {message} · {indexed}
      </p>
      <div className="relative">
        <pre className="text-xs text-foreground leading-relaxed whitespace-pre-wrap font-mono">
          {source.preview}
        </pre>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-background to-transparent" />
      </div>
    </div>
  );
}

interface PreviewPaneProps {
  source: SourceSummary;
  onClose: () => void;
}

function PreviewPane({ source, onClose }: PreviewPaneProps) {
  const [type, setType] = useState<SourceType | null>(null);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fileUrl = useSourceFileUrl(source);
  const hasStoredFile = Boolean(source.file_ext);

  useEffect(() => {
    // Nothing was stored for this source, so there is no file to type-sniff or
    // render. Land on the neutral empty state below rather than the destructive
    // "Preview unavailable" - a YouTube transcript is a healthy source, not a
    // broken one, and the red error read like the ingest had failed.
    if (!hasStoredFile) {
      setIsLoading(false);
      setError(null);
      setType(null);
      setTextContent(null);
      return;
    }
    if (!fileUrl) return;
    setIsLoading(true);
    setError(null);
    setType(null);
    setTextContent(null);

    // Aborted on unmount/source change so a superseded request can't fail late and
    // paint "Preview unavailable" over a preview that actually loaded fine.
    const controller = new AbortController();

    resolveSourceType(source, controller.signal)
      .then(async (detectedType) => {
        setType(detectedType);
        if (detectedType === "text") {
          setTextContent(await fetchTextFile(fileUrl, controller.signal));
        }
        setIsLoading(false);
      })
      .catch((err: Error) => {
        if (err.name === "AbortError") return;
        setError(err.message);
        setIsLoading(false);
      });

    return () => controller.abort();
  }, [source, fileUrl, hasStoredFile]);

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

        {!isLoading && !error && !hasStoredFile && (
          <NoFilePreview
            source={source}
            message="No original file stored for this source"
          />
        )}

        {!isLoading && !error && type === "binary" && (
          <NoFilePreview
            source={source}
            message={`No preview for ${source.file_ext || "this"} files`}
          />
        )}

        {!isLoading && !error && type === "pdf" && fileUrl && (
          <PDFPreview url={fileUrl} />
        )}

        {!isLoading && !error && type === "image" && fileUrl && (
          <div className="flex items-center justify-center p-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={fileUrl}
              alt={source.source}
              crossOrigin="anonymous"
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

// -- Source card ---------------------------------------------------------------

interface SourceCardProps {
  source: SourceSummary;
  isConfirming: boolean;
  onPreview: (source: SourceSummary) => void;
  onRequestDelete: (source: string) => void;
  onConfirmDelete: (source: string) => void;
  onCancelConfirm: () => void;
}

function SourceCard({
  source,
  isConfirming,
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

      {/* No "still ingesting" variant any more: GET /documents/ returns finished
          sources only, so everything in this grid is done. An in-flight job is
          shown in the In progress section above, where it can be cancelled. */}
      {isConfirming && (
        <p className="text-[11px] text-red-600 dark:text-red-400 leading-snug" onClick={(e) => e.stopPropagation()}>
          Delete &lsquo;{source.source}&rsquo;? This cannot be undone.
        </p>
      )}

      {!isConfirming && <SourceThumbnail source={source} />}

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

// -- In-progress section -------------------------------------------------------

const JOB_STATUS_LABELS: Record<string, string> = {
  queued: "Waiting for the worker…",
  ingesting: "Extracting text…",
  building_graph: "Building knowledge graph…",
};

/**
 * Jobs still occupying the ingestion worker, with a cancel control.
 *
 * `GET /documents/` no longer returns mid-build sources, which is what makes the
 * grid below trustworthy - but the reason it used to was real: you need to be
 * able to see a stuck job and get rid of it. That capability lives here instead,
 * driven by the ingestion queue, which is where a job's status and progress
 * actually are. `SourcesPanel` shows the same jobs in the right-hand panel; this
 * exists so the capability survives that panel being collapsed.
 *
 * Cancelling deletes the source's data (the backend's `_cleanup_partial`), which
 * is what the confirm copy has to say - don't soften it to "progress is lost".
 */
function InProgressSection({
  jobs,
  onCancelJob,
}: {
  jobs: IngestionJob[];
  onCancelJob?: (jobId: string) => void;
}) {
  const [pendingCancelId, setPendingCancelId] = useState<string | null>(null);

  if (jobs.length === 0) return null;

  return (
    <div className="border-b border-border px-3 py-2">
      <p className="mb-1.5 px-0.5 text-[11px] font-medium uppercase tracking-wide text-foreground-muted/60">
        In progress · {jobs.length}
      </p>
      <div className="space-y-1">
        {jobs.map((job) => {
          const isConfirming = pendingCancelId === job.id;
          return (
            <div key={job.id} className="rounded-lg border border-border bg-surface px-2.5 py-2">
              <div className="flex items-start gap-2">
                {job.status === "queued" ? (
                  <Hourglass className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-yellow-500 dark:text-yellow-400" />
                ) : job.status === "building_graph" ? (
                  <GitBranch className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-blue-500" />
                ) : (
                  <Loader2 className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 animate-spin text-foreground-muted" />
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-foreground" title={job.source}>
                    {job.source}
                  </p>
                  <p className="text-[10px] text-foreground-muted">
                    {JOB_STATUS_LABELS[job.status] ?? job.status}
                  </p>
                </div>
                {onCancelJob && !isConfirming && (
                  <button
                    onClick={() => setPendingCancelId(job.id)}
                    className="flex-shrink-0 rounded p-0.5 text-foreground-muted hover:text-destructive transition-colors"
                    title="Cancel ingestion"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>
              {isConfirming && (
                <div className="mt-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1.5">
                  <p className="mb-1.5 text-[11px] leading-snug text-foreground">
                    Cancel &lsquo;{job.source}&rsquo;? Everything ingested so far is discarded,
                    including any knowledge graph already built.
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => {
                        onCancelJob?.(job.id);
                        setPendingCancelId(null);
                      }}
                      className="rounded bg-amber-500 px-2 py-0.5 text-[11px] font-medium text-white hover:bg-amber-600 transition-colors"
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
    </div>
  );
}

// -- Modal ---------------------------------------------------------------------

interface SourcesModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSourcesChanged?: () => void;
  /** Every ingestion job; the active ones drive the In progress section. */
  jobs?: IngestionJob[];
  onCancelJob?: (jobId: string) => void;
  /**
   * Dismiss any queue rows belonging to a source that was just deleted. Keyed by
   * source because DELETE /documents/{source} cancels the job without reporting its id.
   */
  onJobsInvalidated?: (source: string) => void;
}

export function SourcesModal({
  isOpen,
  onClose,
  onSourcesChanged,
  jobs,
  onCancelJob,
  onJobsInvalidated,
}: SourcesModalProps) {
  const [sources, setSources] = useState<SourceSummary[]>([]);
  const [isLoadingSources, setIsLoadingSources] = useState(false);
  const [query, setQuery] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [preview, setPreview] = useState<SourceSummary | null>(null);

  const activeJobs = useMemo(
    () => (jobs ?? []).filter((j) => isActiveStatus(j.status)),
    [jobs]
  );

  // Reset the view every time the modal opens.
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

  // Re-fetch when the number of in-flight jobs changes, which matters now that
  // `GET /documents/` is done-only: a job finishing is what *adds* its source to
  // the grid, so without this it would sit in "In progress", disappear, and not
  // reappear until the modal was reopened. Deliberately separate from the effect
  // above - folding it in would reset `preview` and `confirming` too, closing an
  // open preview the moment an unrelated background job finished.
  useEffect(() => {
    if (!isOpen) return;
    fetchSources()
      .then(setSources)
      .catch(() => {
        // Keep the list we already have; a failed refresh is not worth emptying
        // the grid the user is looking at.
      });
  }, [isOpen, activeJobs.length]);

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
        // No separate cancel call first: DELETE /documents/{source} finds the
        // source's active job, cancels it, and only then deletes - one round trip,
        // and no window where the job writes rows between our two requests.
        await apiDeleteSource(source);
        setSources((prev) => prev.filter((s) => s.source !== source));
        setConfirming(null);
        // That endpoint cancels the job for us but returns no job id, so the queue row
        // has to be hidden by source name. Without this, deleting a source mid-build
        // left its now-"cancelled" row in the Ingest panel - the X button's cancel path
        // hides the row itself, and this path used to skip that entirely.
        onJobsInvalidated?.(source);
        onSourcesChanged?.();
      } catch {
        // keep confirming state so user can retry
      }
    },
    [onJobsInvalidated, onSourcesChanged]
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
          // -- Preview mode --------------------------------------------------
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
          // -- Grid mode -----------------------------------------------------
          <>
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-border flex-shrink-0">
              <h2 className="text-sm font-semibold text-foreground">
                Sources
                {/* "N sources", not "N total": the grid is finished sources
                    only, and the in-flight count is carried by its own section
                    below rather than folded into one misleading number. */}
                {!isLoadingSources && (
                  <span className="ml-2 text-xs font-normal text-foreground-muted">
                    {sources.length} source{sources.length !== 1 ? "s" : ""}
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
              <InProgressSection jobs={activeJobs} onCancelJob={onCancelJob} />
              {isLoadingSources ? (
                <div className="flex items-center justify-center gap-2 py-12 text-foreground-muted">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span className="text-sm">Loading sources…</span>
                </div>
              ) : filtered.length === 0 ? (
                <p className="px-4 py-8 text-center text-sm text-foreground-muted">
                  {query
                    ? "No sources match your filter."
                    : activeJobs.length > 0
                      ? "Nothing finished yet — the jobs above are still running."
                      : "No sources ingested yet."}
                </p>
              ) : (
                <div className="grid grid-cols-2 gap-2 p-3">
                  {filtered.map((source) => (
                    <SourceCard
                      key={source.source}
                      source={source}
                      isConfirming={confirming === source.source}
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
