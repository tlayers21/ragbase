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

// One status set, because a job now holds the worker from start to built graph
const ACTIVE_STATUSES = new Set(["queued", "ingesting", "building_graph"]);

/** Whether a job is still occupying the ingestion worker (or waiting for it). */
export function isActiveStatus(status: string): boolean {
  return ACTIVE_STATUSES.has(status);
}

/**
 * Whether the worker has finished with a job, successfully or not.
 *
 * Mirrors `_is_terminal` in `ingestion/queue.py`, and is deliberately not
 * `!isActiveStatus` - an unrecognised status should read as in-progress.
 */
export function isTerminalStatus(status: string): boolean {
  return status === "done" || status === "cancelled" || status.startsWith("error");
}

function hasActiveJobs(jobs: IngestionJob[]): boolean {
  return jobs.some((j) => isActiveStatus(j.status));
}

// Fast while queued so transitions feel immediate; the graph phase is slow and quiet
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

  // Recursive setTimeout so the interval can adapt each cycle
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

  // Adopt the server's jobs once on mount, so a reload does not empty the panel
  useEffect(() => {
    let cancelled = false;
    fetchIngestionStatus()
      .then((status) => {
        if (cancelled) return;
        setJobs(status.jobs);
        if (hasActiveJobs(status.jobs)) startPolling(status.jobs);
      })
      .catch(() => {
        // Best-effort: a failed first poll just leaves the panel empty, as before
      });
    return () => {
      cancelled = true;
    };
  }, [startPolling]);

  // Every terminal status fades, not just "done" - there is no X button to dismiss one
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
    // hiddenJobIds, not a local filter - the next poll would bring the row back
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

  // Matched by source name, because the delete endpoint returns no job id
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
