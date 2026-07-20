"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  ingestFile,
  ingestText as apiIngestText,
  ingestUrl as apiIngestUrl,
  fetchIngestionStatus,
  cancelIngestion,
  clearCompletedJobs,
  getUserId,
} from "@/lib/api";
import { deriveSourceName } from "@/lib/utils";
import type { IngestionJob } from "@/types";

const ACTIVE_STATUSES = new Set(["queued", "ingesting", "ingested", "building_graph"]);

function hasActiveJobs(jobs: IngestionJob[]): boolean {
  return jobs.some((j) => ACTIVE_STATUSES.has(j.status));
}

// Dynamic poll interval: fast while queued so transitions feel immediate.
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

  // Auto-fade done jobs: 30s → opacity-0 (1s transition) → remove from display
  useEffect(() => {
    for (const job of jobs) {
      if (job.status !== "done") continue;
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
    async (file: File) => {
      const sourceName = deriveSourceName(file.name);
      setIsUploading(true);
      setUploadError(null);
      try {
        const result = await ingestFile(file, sourceName);
        const suffixMatch = file.name.match(/\.[^/.]+$/);
        const newJob: IngestionJob = {
          id: result.job_id,
          filename: file.name,
          source: sourceName,
          user_id: getUserId(),
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
    setJobs((prev) => prev.filter((j) => j.id !== jobId));
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
          user_id: getUserId(),
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
          user_id: getUserId(),
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

  const clearCompleted = useCallback(async () => {
    try {
      await clearCompletedJobs();
      // Mirror the server-side filter: remove done, cancelled, and error jobs
      setJobs((prev) =>
        prev.filter(
          (j) => j.status !== "done" && j.status !== "cancelled" && !j.status.startsWith("error")
        )
      );
    } catch {
      // ignore — display is best-effort
    }
  }, []);

  const activeJobCount = jobs.filter((j) => ACTIVE_STATUSES.has(j.status)).length;
  const clearableJobCount = jobs.filter(
    (j) => j.status === "done" || j.status === "cancelled" || j.status.startsWith("error")
  ).length;

  return {
    jobs,
    activeJobCount,
    clearableJobCount,
    fadingJobIds,
    hiddenJobIds,
    isUploading,
    uploadError,
    uploadFile,
    ingestText,
    ingestUrl,
    cancelJob,
    clearCompleted,
  };
}
