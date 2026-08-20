"use client";

import { useEffect, useState } from "react";
import { Loader2, PlugZap } from "lucide-react";
import { cn } from "@/lib/utils";
import type { HealthStatus } from "@/types";

/** How long the fade-out runs. Must match the duration class below. */
const FADE_MS = 300;

/** Width the indeterminate bar sits at while there is no progress to report.
 *  Far enough to read as "working", short of the end so it never looks stuck. */
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
 * There is deliberately no way past it; the backend's `finally` and per-step
 * timeout are what stop it wedging the app shut.
 */
export function WarmupGate({ status, stalled, ready }: WarmupGateProps) {
  // Seeded from `ready` so an already-warm mount renders nothing at all
  const [hidden, setHidden] = useState(ready);

  // Stay mounted through the fade, then stop rendering entirely
  useEffect(() => {
    if (!ready) return;
    const timer = setTimeout(() => setHidden(true), FADE_MS);
    return () => clearTimeout(timer);
  }, [ready]);

  if (hidden) return null;

  const total = status?.total ?? 0;
  const completed = status?.completed ?? 0;
  const hasProgress = total > 0;

  // The in-flight step counts as half, and is clamped because `current` outlives the gate
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

        {/* Always present. The bar is the one thing that must never disappear -
            a gap in it reads as the app having given up. */}
        <div className="w-full space-y-1.5">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface">
            <div
              className={cn(
                "h-full rounded-full transition-[width] duration-500 ease-out",
                // Stop animating - a sweeping bar with nothing happening is a lie
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
            "Chat and uploads open automatically - running them now would queue behind the models and stall."
          )}
        </p>
      </div>
    </div>
  );
}
