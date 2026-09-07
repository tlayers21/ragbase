"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  cancelAnalysis,
  checkSourceContradictions,
  checkSourceFacts,
  fetchAnalysisStatus,
} from "@/lib/api";
import { ANALYSIS_POLL_INTERVAL_MS } from "@/lib/config";
import type { AnalysisKind, AnalysisResult, AnalysisRun } from "@/types";

/**
 * Drive the two per-source checks, which run for minutes behind one open POST.
 *
 * Two separate channels, and keeping them separate is the whole design:
 *
 * - the **POST** (`checkSourceFacts` / `checkSourceContradictions`) resolves once,
 *   at the end, with the totals. It is the authority on "this run is over".
 * - the **poll** of `GET /documents/analysis/status` supplies "chunk 40 of 210"
 *   while that request is still open, and is the only thing a reloaded tab has.
 *
 * Only one run exists process-wide, so a second start is refused by the backend
 * with a 409 rather than queued. When that happens the hook adopts the run that
 * actually holds the slot: "a check is already running" is not useful on its own,
 * "'notes.pdf' is on chunk 12 of 88" tells the user what to wait for.
 */
export function useAnalysis(onFinished?: () => void) {
  const [run, setRun] = useState<AnalysisRun | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollingRef = useRef(false);
  // Whether *this tab* has a POST in flight. While it does, only that POST ends
  // the run - a poll that races ahead of the backend claiming the slot would
  // otherwise see null on the first tick and stop before any progress arrived.
  const ownRunRef = useRef(false);

  // Held in a ref so the poll loop is not rebuilt when the caller re-renders
  const onFinishedRef = useRef(onFinished);
  useEffect(() => {
    onFinishedRef.current = onFinished;
  }, [onFinished]);

  const stopPolling = useCallback(() => {
    pollingRef.current = false;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const scheduleNext = useCallback(() => {
    if (!pollingRef.current) return;
    timerRef.current = setTimeout(async () => {
      try {
        const status = await fetchAnalysisStatus();
        if (status.run) {
          setRun(status.run);
        } else if (!ownRunRef.current) {
          // An adopted run - another tab's, or this one's from before a reload -
          // has ended, and there is no POST coming to tell us the totals
          stopPolling();
          setRun(null);
          onFinishedRef.current?.();
          return;
        }
      } catch {
        // A failed poll says nothing about the run; the next tick retries
      }
      scheduleNext();
    }, ANALYSIS_POLL_INTERVAL_MS);
  }, [stopPolling]);

  const startPolling = useCallback(() => {
    if (pollingRef.current) return;
    pollingRef.current = true;
    scheduleNext();
  }, [scheduleNext]);

  /** Pick up a run already in flight. Called when the sources modal opens. */
  const adopt = useCallback(async () => {
    try {
      const status = await fetchAnalysisStatus();
      if (status.run) {
        setRun(status.run);
        startPolling();
      }
    } catch {
      // The modal opening must not fail because the backend is unreachable
    }
  }, [startPolling]);

  const start = useCallback(
    async (source: string, kind: AnalysisKind) => {
      if (ownRunRef.current) return;

      setError(null);
      setResult(null);
      // Optimistic, so the button flips on click rather than a poll later. total 0
      // renders as an indeterminate bar until the backend reports the chunk count.
      setRun({
        source,
        kind,
        current: 0,
        total: 0,
        found: 0,
        cancelled: false,
        elapsed_seconds: 0,
      });
      ownRunRef.current = true;
      startPolling();

      try {
        const check = kind === "facts" ? checkSourceFacts : checkSourceContradictions;
        setResult(await check(source));
        setRun(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "The check failed");
        setRun(null);
        // A 409 means something else holds the slot - show what, rather than
        // leaving the user with a refusal and no way to see the cause
        void adopt();
      } finally {
        ownRunRef.current = false;
        stopPolling();
        onFinishedRef.current?.();
      }
    },
    [adopt, startPolling, stopPolling]
  );

  /**
   * Ask the backend to stop after the chunk it is on.
   *
   * The POST stays open until it does, so this does not resolve the run - it
   * flips the local flag to `cancelled` and the copy with it. A model call
   * already in flight is not interrupted, so "Stopping" is honest: it is seconds
   * away, not immediate.
   */
  const stop = useCallback(async () => {
    if (!run) return;
    setRun({ ...run, cancelled: true });
    try {
      await cancelAnalysis(run.source);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel the check");
    }
  }, [run]);

  const dismissResult = useCallback(() => {
    setResult(null);
    setError(null);
  }, []);

  return { run, result, error, start, stop, adopt, dismissResult };
}
