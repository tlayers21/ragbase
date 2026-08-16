"use client";

import { useEffect, useState } from "react";
import { Loader2, PlugZap } from "lucide-react";
import { cn } from "@/lib/utils";
import type { HealthStatus } from "@/types";

/** How long the fade-out runs. Must match the duration class below. */
const FADE_MS = 300;

/** Width the indeterminate bar sits at while there's no progress to report.
 *  Far enough along to read as "working", short of the end so it doesn't look
 *  stuck at completion. (The ingest panel's bars no longer park like this —
 *  every phase there has an estimate to animate against.) */
const INDETERMINATE_WIDTH = "65%";

/** Warmup step keys (config/settings.py::WARMUP_CRITICAL_TASKS) as prose. */
const STEP_LABELS: Record<string, string> = {
  embed: "embedding model",
  answer: "answer model",
  reranker: "reranker",
  summarize: "summarizer",
  vision_simple: "vision model",
};

interface WarmupGateProps {
  status: HealthStatus | null;
  /** True once the backend has been unreachable long enough to be worth explaining. */
  stalled: boolean;
  /** Drives the fade-out. The gate unmounts itself once the transition ends. */
  ready: boolean;
}

/**
 * Full-screen cover shown while the backend loads its models.
 *
 * It exists because the app used to look usable the moment the server bound its
 * port: sending a query or dropping a file during warmup put the request behind
 * several gigabytes of model loading on the same GPU, which reads as a hang or
 * an error. Covering the whole app — not just disabling the chat input — is
 * deliberate; uploads and source deletion hit the same contention.
 *
 * **There is no way past it.** An earlier version had a "continue anyway" button;
 * it only ever led to a query that stalled, so it was removed. Nothing here can
 * wedge the app shut permanently: the backend marks a warmup step finished in a
 * `finally` (so a model that fails to load still lifts the gate) and bounds each
 * step with a timeout (so one that *hangs* does too).
 */
export function WarmupGate({ status, stalled, ready }: WarmupGateProps) {
  const [hidden, setHidden] = useState(false);

  // Stay mounted through the fade, then stop rendering entirely.
  useEffect(() => {
    if (!ready) return;
    const timer = setTimeout(() => setHidden(true), FADE_MS);
    return () => clearTimeout(timer);
  }, [ready]);

  if (hidden) return null;

  const total = status?.total ?? 0;
  const completed = status?.completed ?? 0;
  const hasProgress = total > 0;

  // The step in flight counts as half a step. Progress is otherwise flat at 0%
  // for the whole of the first (slowest) load, which reads as nothing happening.
  //
  // Clamped because `current` outlives the gate: once the critical group is done
  // the backend moves on to the ingestion-only models, so /health briefly reports
  // completed === total *and* a current step — which lands at 117% without this.
  const percent = hasProgress
    ? Math.min(100, Math.round(((completed + (status?.current ? 0.5 : 0)) / total) * 100))
    : 0;
  const stepLabel = status?.current ? (STEP_LABELS[status.current] ?? status.current) : null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="RAGbase startup"
      className={cn(
        "fixed inset-0 z-50 flex items-center justify-center bg-background p-6",
        "transition-opacity ease-out",
        ready && "opacity-0 pointer-events-none"
      )}
      style={{ transitionDuration: `${FADE_MS}ms` }}
    >
      <div className="flex w-full max-w-sm flex-col items-center gap-4 text-center">
        {stalled ? (
          <PlugZap className="h-6 w-6 text-foreground-muted" />
        ) : (
          <Loader2 className="h-6 w-6 animate-spin text-foreground-muted" />
        )}

        <div className="space-y-1.5">
          <h1 className="text-base font-semibold text-foreground">
            {stalled ? "Can't reach the backend" : "Starting RAGbase"}
          </h1>
          <p className="text-sm text-foreground-muted">
            {stalled
              ? "It hasn't responded yet. Check that the backend is running and that Ollama is started."
              : stepLabel
                ? `Loading the ${stepLabel}…`
                : "Waiting for the backend…"}
          </p>
        </div>

        {/* Always present. The bar is the one thing that must never disappear —
            a gap in it reads as the app having given up. */}
        <div className="w-full space-y-1.5">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface">
            <div
              className={cn(
                "h-full rounded-full transition-[width] duration-500 ease-out",
                // Stalled: stop animating. A bar that keeps sweeping while
                // nothing is happening is a lie about the app's state.
                stalled ? "bg-foreground-muted/30" : "bg-primary progress-shimmer"
              )}
              style={{ width: hasProgress ? `${percent}%` : INDETERMINATE_WIDTH }}
            />
          </div>
          <p className="text-xs text-foreground-muted">
            {stalled
              ? "Not responding"
              : hasProgress
                ? `${completed} of ${total} models ready`
                : "Connecting…"}
          </p>
        </div>

        <p className="text-xs text-foreground-muted">
          {stalled ? (
            <>
              Settings are still reachable at{" "}
              <a href="/settings" className="underline hover:text-foreground">
                /settings
              </a>{" "}
              if the API URL needs changing.
            </>
          ) : (
            "Chat and uploads open automatically — running them now would queue behind the models and stall."
          )}
        </p>
      </div>
    </div>
  );
}
