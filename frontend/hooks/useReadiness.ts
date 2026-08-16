"use client";

import { useEffect, useRef, useState } from "react";
import { fetchHealth } from "@/lib/api";
import { HEALTH_POLL_INTERVAL_MS, HEALTH_STALL_AFTER_MS } from "@/lib/config";
import type { HealthStatus } from "@/types";

// Latched at module scope, deliberately outside the hook. `useReadiness` is called
// from app/page.tsx, and /settings is a sibling route segment - navigating there
// unmounts the page and destroys this hook's state, so coming back re-mounted it
// with `status: null` and flashed the full "Connecting..." gate for a round trip
// plus its 300ms fade. Warmup never runs twice in one backend process, so once
// we've seen ready there is nothing to re-check; remembering it here makes a route
// return instant while a cold first load still gates normally.
//
// This adds no staleness that didn't already exist: the poll below stops forever
// on the first ready response, so a backend restarted mid-session already leaves
// the tab believing it is warm.
let latchedReady = false;
let latchedStatus: HealthStatus | null = null;

/**
 * Polls GET /health until the backend finishes its startup warmup.
 *
 * The backend answers requests immediately but spends the first stretch of its
 * life loading models; anything the user does in that window competes with the
 * warmup for the same GPU and stalls or times out. This hook is what lets the
 * UI stay closed until a query can actually be served (see WarmupGate).
 *
 * Polling stops as soon as the backend reports ready - there is no way back to
 * "warming" without a restart, which reloads the page's state anyway.
 */
export function useReadiness() {
  const [status, setStatus] = useState<HealthStatus | null>(latchedStatus);
  const [stalled, setStalled] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // Already known warm from an earlier mount - don't re-poll, don't re-gate.
    if (latchedReady) return;

    let cancelled = false;

    // Fires only if we never reach the backend at all. Cleared on the first
    // success, so a blip midway through a warmup that is visibly progressing
    // can't trip the "can't reach the backend" copy.
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
        // The backend is usually just not up yet; keep polling so launching the
        // two servers in either order still converges. `stalled` above is the
        // observable signal if it never comes up, so there's nothing to record
        // here - an error string was kept for a while and rendered nowhere.
        //
        // `status` is deliberately NOT cleared. Blanking it on a transient
        // failure threw away the last known completed/total and collapsed the
        // gate's progress bar back to the indeterminate state mid-warmup, which
        // reads as the load having restarted.
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
    // `ready !== false` rather than `=== true`: a backend that predates the
    // warmup fields reports neither, and gating forever on a missing key would
    // be worse than letting it through.
    ready: status !== null && status.ready !== false,
    /** No successful /health response yet after HEALTH_STALL_AFTER_MS - the
     *  backend is probably not running. Switches the gate's copy, nothing else. */
    stalled,
    status,
  };
}
