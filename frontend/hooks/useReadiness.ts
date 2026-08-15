"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchHealth } from "@/lib/api";
import { HEALTH_POLL_INTERVAL_MS } from "@/lib/config";
import type { HealthStatus } from "@/types";

/**
 * Polls GET /health until the backend finishes its startup warmup.
 *
 * The backend answers requests immediately but spends the first stretch of its
 * life loading models; anything the user does in that window competes with the
 * warmup for the same GPU and stalls or times out. This hook is what lets the
 * UI stay closed until a query can actually be served (see WarmupGate).
 *
 * Polling stops as soon as the backend reports ready — there is no way back to
 * "warming" without a restart, which reloads the page's state anyway.
 */
export function useReadiness() {
  const [status, setStatus] = useState<HealthStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const next = await fetchHealth();
        if (cancelled) return;
        setStatus(next);
        setError(null);
        if (next.ready !== false) return; // warm — stop polling
      } catch (err) {
        // The backend is usually just not up yet; keep polling so launching the
        // two servers in either order still converges.
        if (cancelled) return;
        setStatus(null);
        setError(err instanceof Error ? err.message : "Backend unreachable");
      }
      timerRef.current = setTimeout(poll, HEALTH_POLL_INTERVAL_MS);
    };

    poll();

    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const dismiss = useCallback(() => setDismissed(true), []);

  return {
    // `ready !== false` rather than `=== true`: a backend that predates the
    // warmup fields reports neither, and gating forever on a missing key would
    // be worse than letting it through.
    ready: status !== null && status.ready !== false,
    /** Whether the first health response (or failure) has landed. Until it has,
     *  the gate renders nothing — otherwise an already-warm backend flashes it. */
    checked: status !== null || error !== null,
    status,
    error,
    dismissed,
    dismiss,
  };
}
