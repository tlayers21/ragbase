"use client";

import { useEffect, useRef, useState } from "react";
import { fetchHealth } from "@/lib/api";
import { HEALTH_POLL_INTERVAL_MS, HEALTH_STALL_AFTER_MS } from "@/lib/config";
import type { HealthStatus } from "@/types";

// Module scope so a route change back from /settings does not re-flash the gate
let latchedReady = false;
let latchedStatus: HealthStatus | null = null;

/**
 * Polls GET /health until the backend finishes its startup warmup.
 *
 * Polling stops for good on the first ready response - there is no way back to
 * "warming" without a restart.
 */
export function useReadiness() {
  const [status, setStatus] = useState<HealthStatus | null>(latchedStatus);
  const [stalled, setStalled] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // Already known warm from an earlier mount - don't re-poll, don't re-gate
    if (latchedReady) return;

    let cancelled = false;

    // Cleared on the first success, so a blip mid-warmup cannot trip the error copy
    const stallTimer = setTimeout(() => {
      if (!cancelled) setStalled(true);
    }, HEALTH_STALL_AFTER_MS);

    const poll = async () => {
      try {
        const next = await fetchHealth();
        if (cancelled) return;
        clearTimeout(stallTimer);
        latchedStatus = next;
        setStatus(next);
        setStalled(false);
        if (next.ready !== false) {
          latchedReady = true;
          return; // warm - stop polling
        }
      } catch {
        // `status` is deliberately not cleared - blanking it collapses the progress bar
        if (cancelled) return;
      }
      timerRef.current = setTimeout(poll, HEALTH_POLL_INTERVAL_MS);
    };

    poll();

    return () => {
      cancelled = true;
      clearTimeout(stallTimer);
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return {
    // `!== false`, so a backend without the warmup fields is not gated forever
    ready: status !== null && status.ready !== false,
    /** No successful /health response yet after HEALTH_STALL_AFTER_MS - the
     *  backend is probably not running. Switches the gate's copy, nothing else. */
    stalled,
    status,
  };
}
