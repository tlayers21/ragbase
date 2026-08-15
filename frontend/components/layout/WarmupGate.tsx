"use client";

import { useEffect, useState } from "react";
import { Loader2, PlugZap } from "lucide-react";
import type { HealthStatus } from "@/types";

/** Milliseconds before the escape hatch appears — long enough that a normal
 *  warmup finishes first, short enough that a wedged model isn't a dead end. */
const DISMISS_AFTER_MS = 10000;

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
  error: string | null;
  onDismiss: () => void;
}

/**
 * Full-screen cover shown while the backend loads its models.
 *
 * It exists because the app used to look usable the moment the server bound its
 * port: sending a query or dropping a file during warmup put the request behind
 * several gigabytes of model loading on the same GPU, which reads as a hang or
 * an error. Covering the whole app — not just disabling the chat input — is
 * deliberate; uploads and source deletion hit the same contention.
 */
export function WarmupGate({ status, error, onDismiss }: WarmupGateProps) {
  const [canDismiss, setCanDismiss] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setCanDismiss(true), DISMISS_AFTER_MS);
    return () => clearTimeout(timer);
  }, []);

  const total = status?.total ?? 0;
  const completed = status?.completed ?? 0;
  // The step in flight counts as half a step. Progress is otherwise flat at 0%
  // for the whole of the first (slowest) load, which reads as nothing happening.
  const progress = total > 0 ? (completed + (status?.current ? 0.5 : 0)) / total : 0;
  const percent = Math.round(progress * 100);
  const stepLabel = status?.current ? (STEP_LABELS[status.current] ?? status.current) : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background p-6">
      <div className="flex w-full max-w-sm flex-col items-center gap-4 text-center">
        {error ? (
          <PlugZap className="h-6 w-6 text-foreground-muted" />
        ) : (
          <Loader2 className="h-6 w-6 animate-spin text-foreground-muted" />
        )}

        <div className="space-y-1.5">
          <h1 className="text-base font-semibold text-foreground">
            {error ? "Waiting for the backend" : "Warming up RAGbase"}
          </h1>
          <p className="text-sm text-foreground-muted">
            {error
              ? "Can't reach the API yet — retrying every second."
              : stepLabel
                ? `Loading the ${stepLabel}…`
                : "Loading models into memory…"}
          </p>
        </div>

        {!error && total > 0 && (
          <div className="w-full space-y-1.5">
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface">
              <div
                className="progress-shimmer h-full rounded-full bg-primary transition-[width] duration-500 ease-out"
                style={{ width: `${percent}%` }}
              />
            </div>
            <p className="text-xs text-foreground-muted">
              {completed} of {total} ready
            </p>
          </div>
        )}

        <p className="text-xs text-foreground-muted">
          Chat and uploads open automatically — running them now would queue behind the
          models and stall.
        </p>

        {(canDismiss || error) && (
          <button
            type="button"
            onClick={onDismiss}
            className="rounded-lg border border-border px-3 py-1.5 text-xs text-foreground-muted hover:bg-surface hover:text-foreground transition-colors"
          >
            Continue anyway
          </button>
        )}
      </div>
    </div>
  );
}
