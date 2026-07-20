"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchSources, deleteSource as apiDeleteSource } from "@/lib/api";
import type { SourceSummary } from "@/types";

export function useSources() {
  const [sources, setSources] = useState<SourceSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchSources();
      setSources(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch sources");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const deleteSource = useCallback(
    async (source: string) => {
      try {
        await apiDeleteSource(source);
        setSources((prev) => prev.filter((s) => s.source !== source));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Delete failed");
      }
    },
    []
  );

  return { sources, isLoading, error, refresh, deleteSource };
}
