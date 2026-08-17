"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  ingestFile,
  ingestText as apiIngestText,
  ingestUrl as apiIngestUrl,
  fetchIngestionStatus,
  cancelIngestion,
} from "@/lib/api";
import { deriveSourceName } from "@/lib/utils";
import type { IngestionJob } from "@/types";

// One status set, because there is now one lifecycle: a job holds the single
// worker from the moment it starts until its knowledge graph is built. There used
// to be a second, narrower set for "the machine is actually busy" - extraction and
// the graph ran on separate queues, so `ingested`/`waiting_for_graph` were hand-off
// states with nothing running. Both are gone, and so is the distinction.
const ACTIVE_STATUSES = new Set(["queued", "ingesting", "building_graph"]);

/** Whether a job is still occupying the ingestion worker (or waiting for it). */
export function isActiveStatus(status: string): boolean {
  return ACTIVE_STATUSES.has(status);
}

/**
 * Whether the worker has finished with a job, successfully or not.
 *
 * Mirrors `_is_terminal` in `ingestion/queue.py`; `error: <msg>` carries its message,
 * so it is matched by prefix. Not simply `!isActiveStatus` - an unrecognised status
 * from a newer backend should read as in-progress rather than silently finished.
 */
export function isTerminalStatus(status: string): boolean {
  return status === "done" || status === "cancelled" || status.startsWith("error");
}

function hasActiveJobs(jobs: IngestionJob[]): boolean {
  return jobs.some((j) => isActiveStatus(j.status));
}

// Dynamic poll interval: fast while queued so transitions feel immediate. The
// graph phase is the slow one and has nothing to report between chunks.
function pollInterval(jobs: IngestionJob[]): number {
  if (jobs.some((j) => j.status === "queued")) return 1000;
  if (jobs.some((j) => j.status === "ingesting")) return 2000;
  return 3000;
}

export function useIngestion(onComplete?: () => void) {
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [fadingJobIds, setFadingJobIds] = useState<Set<string>>(new Set());
  const [hiddenJobIds, setHiddenJobIds] = useState<Set<string>>(new Set());
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeRef = useRef(false);
  const processedDoneIds = useRef<Set<string>>(new Set());
  const fadeTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>[]>>(new Map());

  const stopPolling = useCallback(() => {
    activeRef.current = false;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Recursive setTimeout so the interval can adapt each cycle.
  const scheduleNext = useCallback(
    (currentJobs: IngestionJob[]) => {
      if (!activeRef.current) return;
      timerRef.current = setTimeout(async () => {
        try {
          const status = await fetchIngestionStatus();
          setJobs(status.jobs);
          if (!hasActiveJobs(status.jobs)) {
            stopPolling();
            onComplete?.();
          } else {
            scheduleNext(status.jobs);
          }
        } catch {
          // silently ignore poll errors
          scheduleNext(currentJobs);
        }
      }, pollInterval(currentJobs));
    },
    [onComplete, stopPolling]
  );

  const startPolling = useCallback(
    (currentJobs: IngestionJob[]) => {
      if (activeRef.current) return;
      activeRef.current = true;
      scheduleNext(currentJobs);
    },
    [scheduleNext]
  );

  useEffect(() => () => stopPolling(), [stopPolling]);

  // Adopt whatever the server already has, once, on mount.
  //
  // Polling used to start only from uploadFile/ingestText/ingestUrl, so the panel
  // knew about jobs *this tab* had started and nothing else. Reload the page while
  // a large PDF was ingesting and the Ingest panel came back empty - no progress
  // bar, no cancel button - while the worker kept running; a job that had failed
  // was equally invisible, and with no rows there was no "clear finished" button
  // to dismiss its error either. `startPolling` is a no-op if a loop is already
  // running, and every dependency here is a stable useCallback, so this runs once.
  useEffect(() => {
    let cancelled = false;
    fetchIngestionStatus()
      .then((status) => {
        if (cancelled) return;
        setJobs(status.jobs);
        if (hasActiveJobs(status.jobs)) startPolling(status.jobs);
      })
      .catch(() => {
        // Best-effort: a failed first poll just leaves the panel empty, as before.
      });
    return () => {
      cancelled = true;
    };
  }, [startPolling]);

  // Auto-fade finished jobs: 30s -> opacity-0 (1s transition) -> remove from display.
  // Every terminal status fades, not just "done". Cancelled and errored rows used to be
  // excluded, so they sat in the panel indefinitely with no way to dismiss them - the X
  // button is only rendered for cancellable (i.e. still active) jobs.
  useEffect(() => {
    for (const job of jobs) {
      if (!isTerminalStatus(job.status)) continue;
      if (processedDoneIds.current.has(job.id)) continue;
      processedDoneIds.current.add(job.id);
      const id = job.id;
      const t1 = setTimeout(() => {
        setFadingJobIds((prev) => new Set([...prev, id]));
      }, 30_000);
      const t2 = setTimeout(() => {
        setFadingJobIds((prev) => { const n = new Set(prev); n.delete(id); return n; });
        setHiddenJobIds((prev) => new Set([...prev, id]));
        fadeTimersRef.current.delete(id);
      }, 31_000);
      fadeTimersRef.current.set(id, [t1, t2]);
    }
  }, [jobs]);

  // Clean up fade timers on unmount
  useEffect(() => {
    return () => {
      for (const timers of fadeTimersRef.current.values()) {
        timers.forEach(clearTimeout);
      }
    };
  }, []);

  const uploadFile = useCallback(
    async (file: File, describeImages = false) => {
      const sourceName = deriveSourceName(file.name);
      setIsUploading(true);
      setUploadError(null);
      try {
        const result = await ingestFile(file, sourceName, describeImages);
        const suffixMatch = file.name.match(/\.[^/.]+$/);
        const newJob: IngestionJob = {
          id: result.job_id,
          filename: file.name,
          source: sourceName,
          suffix: suffixMatch ? suffixMatch[0].toLowerCase() : "",
          status: result.status,
        };
        setJobs((prev) => {
          const next = [...prev, newJob];
          startPolling(next);
          return next;
        });
      } catch (err) {
        setUploadError(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setIsUploading(false);
      }
    },
    [startPolling]
  );

  const cancelJob = useCallback(async (jobId: string) => {
    // hiddenJobIds (not a local jobs filter) is what keeps it hidden - the next
    // status poll would otherwise bring the now-"cancelled" job right back.
    setHiddenJobIds((prev) => new Set([...prev, jobId]));
    try {
      await cancelIngestion(jobId);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Cancel failed");
    }
  }, []);

  const ingestText = useCallback(
    async (text: string, sourceName: string) => {
      setUploadError(null);
      try {
        const result = await apiIngestText(text, sourceName);
        const newJob: IngestionJob = {
          id: result.job_id,
          filename: sourceName,
          source: sourceName,
          suffix: ".txt",
          status: result.status,
        };
        setJobs((prev) => {
          const next = [...prev, newJob];
          startPolling(next);
          return next;
        });
      } catch (err) {
        setUploadError(err instanceof Error ? err.message : "Ingest failed");
        throw err;
      }
    },
    [startPolling]
  );

  const ingestUrl = useCallback(
    async (url: string) => {
      setUploadError(null);
      try {
        const result = await apiIngestUrl(url);
        const newJob: IngestionJob = {
          id: result.job_id,
          filename: result.source,
          source: result.source,
          suffix: ".url",
          status: result.status,
        };
        setJobs((prev) => {
          const next = [...prev, newJob];
          startPolling(next);
          return next;
        });
      } catch (err) {
        setUploadError(err instanceof Error ? err.message : "Ingest failed");
        throw err;
      }
    },
    [startPolling]
  );

  // Deleting a source goes through the documents API, which cancels the job for us but
  // never tells the caller its id - so the delete path had no way to hide the row the
  // way cancelJob does, and a source deleted mid-build left its "cancelled" row on
  // screen. Match by source name instead, which is what the caller does have.
  const hideJobsForSource = useCallback(
    (source: string) => {
      const ids = jobs.filter((j) => j.source === source).map((j) => j.id);
      if (ids.length === 0) return;
      setHiddenJobIds((prev) => new Set([...prev, ...ids]));
    },
    [jobs]
  );

  const activeJobCount = jobs.filter((j) => isActiveStatus(j.status)).length;

  return {
    jobs,
    activeJobCount,
    fadingJobIds,
    hiddenJobIds,
    isUploading,
    uploadError,
    uploadFile,
    ingestText,
    ingestUrl,
    cancelJob,
    hideJobsForSource,
  };
}
