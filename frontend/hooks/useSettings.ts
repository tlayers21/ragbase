"use client";

import { useState, useEffect, useCallback } from "react";
import { DEFAULT_API_URL } from "@/lib/config";
import {
  fetchUserSettings,
  saveDisplayName,
  setTelemetryEnabled as apiSetTelemetryEnabled,
} from "@/lib/api";

export function useSettings() {
  const [apiUrl, setApiUrlState] = useState(DEFAULT_API_URL);
  const [userId, setUserId] = useState<string | null>(null);
  const [displayName, setDisplayNameState] = useState("");
  const [telemetryEnabled, setTelemetryEnabledState] = useState(true);

  useEffect(() => {
    setApiUrlState(localStorage.getItem("ragbase_api_url") ?? DEFAULT_API_URL);
    setTelemetryEnabledState(localStorage.getItem("ragbase_telemetry") !== "off");
    fetchUserSettings()
      .then((user) => {
        setUserId(user.user_id);
        setDisplayNameState(user.display_name ?? "");
      })
      .catch(() => {
        // Backend unreachable — leave defaults, greeting simply won't show.
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
      // Non-blocking — keep the local value, backend will pick it up next save.
    }
  }, []);

  const setTelemetryEnabled = useCallback(async (enabled: boolean) => {
    setTelemetryEnabledState(enabled);
    // Mirror to localStorage so the toggle renders correctly before the fetch resolves.
    localStorage.setItem("ragbase_telemetry", enabled ? "on" : "off");
    try {
      await apiSetTelemetryEnabled(enabled);
    } catch {
      // Non-blocking — backend applies it on the next successful call.
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
  };
}
