"use client";

import { useState, useEffect, useCallback } from "react";
import { DEFAULT_API_URL, DEFAULT_RELEVANCE_PERCENT } from "@/lib/config";
import {
  fetchUserSettings,
  saveDisplayName,
  setRerankerThreshold,
  setTelemetryEnabled as apiSetTelemetryEnabled,
} from "@/lib/api";
import { relevancePercent, scoreFromRelevancePercent } from "@/lib/utils";

export function useSettings() {
  const [apiUrl, setApiUrlState] = useState(DEFAULT_API_URL);
  const [userId, setUserId] = useState<string | null>(null);
  const [displayName, setDisplayNameState] = useState("");
  const [telemetryEnabled, setTelemetryEnabledState] = useState(true);
  // Held as the displayed percentage, converted to a logit only when saving -
  // the slider, the note beside it and the match badges then all speak one unit.
  const [rerankerPercent, setRerankerPercentState] = useState(DEFAULT_RELEVANCE_PERCENT);

  useEffect(() => {
    setApiUrlState(localStorage.getItem("ragbase_api_url") ?? DEFAULT_API_URL);
    setTelemetryEnabledState(localStorage.getItem("ragbase_telemetry") !== "off");
    fetchUserSettings()
      .then((user) => {
        setUserId(user.user_id);
        setDisplayNameState(user.display_name ?? "");
        // Read from the backend rather than mirrored to localStorage: it is the
        // side that actually applies the threshold, so anything else can drift.
        if (typeof user.reranker_min_score === "number") {
          setRerankerPercentState(relevancePercent(user.reranker_min_score));
        }
      })
      .catch(() => {
        // Backend unreachable - leave defaults, greeting simply won't show.
      });
  }, []);

  function setApiUrl(value: string) {
    localStorage.setItem("ragbase_api_url", value);
    setApiUrlState(value);
  }

  const setDisplayName = useCallback(async (value: string) => {
    setDisplayNameState(value);
    try {
      await saveDisplayName(value);
    } catch {
      // Non-blocking - keep the local value, backend will pick it up next save.
    }
  }, []);

  const setTelemetryEnabled = useCallback(async (enabled: boolean) => {
    setTelemetryEnabledState(enabled);
    // Mirror to localStorage so the toggle renders correctly before the fetch resolves.
    localStorage.setItem("ragbase_telemetry", enabled ? "on" : "off");
    try {
      await apiSetTelemetryEnabled(enabled);
    } catch {
      // Non-blocking - backend applies it on the next successful call.
    }
  }, []);

  // Callers commit on release, not on every drag frame: each save writes
  // data/settings.json and clears the semantic cache server-side.
  const setRerankerPercent = useCallback(async (percent: number) => {
    setRerankerPercentState(percent);
    try {
      await setRerankerThreshold(scoreFromRelevancePercent(percent));
    } catch {
      // Non-blocking - the local value stands, backend picks it up on the next save.
    }
  }, []);

  return {
    apiUrl,
    setApiUrl,
    userId,
    displayName,
    setDisplayName,
    telemetryEnabled,
    setTelemetryEnabled,
    rerankerPercent,
    setRerankerPercent,
  };
}
