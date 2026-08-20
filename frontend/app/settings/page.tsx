"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Save } from "lucide-react";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { useSettings } from "@/hooks/useSettings";
import { DEFAULT_API_URL, DEFAULT_RELEVANCE_PERCENT } from "@/lib/config";

export default function SettingsPage() {
  const {
    apiUrl,
    setApiUrl,
    displayName,
    setDisplayName,
    telemetryEnabled,
    setTelemetryEnabled,
    rerankerPercent,
    setRerankerPercent,
  } = useSettings();
  const [localDisplayName, setLocalDisplayName] = useState(displayName);
  const [localApiUrl, setLocalApiUrl] = useState(apiUrl);
  // Tracks the drag so the readout moves with the thumb; the commit happens on
  // release, in setRerankerPercent.
  const [localRerankerPercent, setLocalRerankerPercent] = useState(rerankerPercent);
  const [saved, setSaved] = useState(false);

  // Sync once the backend-fetched values arrive.
  useEffect(() => setLocalDisplayName(displayName), [displayName]);
  useEffect(() => setLocalApiUrl(apiUrl), [apiUrl]);
  useEffect(() => setLocalRerankerPercent(rerankerPercent), [rerankerPercent]);

  function handleSave() {
    setDisplayName(localDisplayName.trim());
    setApiUrl(localApiUrl.trim() || DEFAULT_API_URL);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div className="mx-auto max-w-lg px-4 py-8">
      {/* Back */}
      <Link
        href="/"
        className="mb-8 inline-flex items-center gap-2 text-sm text-foreground-muted hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to chat
      </Link>

      <h1 className="text-2xl font-bold text-foreground mb-6">Settings</h1>

      <div className="space-y-6">
        {/* Display name */}
        <div className="rounded-xl border border-border bg-surface p-5">
          <label className="block text-sm font-semibold text-foreground mb-1">
            Display name
          </label>
          <p className="text-xs text-foreground-muted mb-3">
            Optional. Used for a friendly greeting - never sent anywhere.
          </p>
          <input
            type="text"
            value={localDisplayName}
            onChange={(e) => setLocalDisplayName(e.target.value)}
            onBlur={() => setDisplayName(localDisplayName.trim())}
            placeholder="e.g. Tommy"
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-foreground-muted outline-none focus:border-primary/60 focus:ring-1 focus:ring-ring transition-shadow"
          />
        </div>

        {/* API URL */}
        <div className="rounded-xl border border-border bg-surface p-5">
          <label className="block text-sm font-semibold text-foreground mb-1">
            API URL
          </label>
          <p className="text-xs text-foreground-muted mb-3">
            Base URL of the RAGbase FastAPI server. Defaults to{" "}
            <code className="font-mono text-primary">{DEFAULT_API_URL}</code>.
          </p>
          <input
            type="url"
            value={localApiUrl}
            onChange={(e) => setLocalApiUrl(e.target.value)}
            placeholder={DEFAULT_API_URL}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-foreground-muted outline-none focus:border-primary/60 focus:ring-1 focus:ring-ring transition-shadow"
          />
        </div>

        {/* Telemetry */}
        <div className="rounded-xl border border-border bg-surface p-5">
          <div className="flex items-center justify-between gap-4">
            <label
              htmlFor="telemetry-toggle"
              className="text-sm font-semibold text-foreground cursor-pointer"
            >
              Send anonymous usage telemetry
            </label>
            <button
              id="telemetry-toggle"
              role="switch"
              aria-checked={telemetryEnabled}
              onClick={() => setTelemetryEnabled(!telemetryEnabled)}
              className={`relative h-6 w-11 flex-shrink-0 overflow-hidden rounded-full transition-colors ${
                telemetryEnabled ? "bg-primary" : "bg-border"
              }`}
            >
              {/* left-0 anchors the knob to the track. Without it the absolute
                  span falls back to its static position - the button centers its
                  content - so translate-x pushed the knob off the right edge. */}
              <span
                className={`absolute left-0 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                  telemetryEnabled ? "translate-x-[22px]" : "translate-x-0.5"
                }`}
              />
            </button>
          </div>
          <p className="text-xs text-foreground-muted mt-2">
            Sends anonymous usage data (query latency, source counts) to help improve
            RAGbase. No queries, documents, or personal data are ever sent.
          </p>
        </div>

        {/* Retrieval threshold */}
        <div className="rounded-xl border border-border bg-surface p-5">
          <div className="flex items-baseline justify-between gap-4 mb-1">
            <label htmlFor="relevance-threshold" className="text-sm font-semibold text-foreground">
              Minimum relevance
            </label>
            <span className="text-sm font-mono text-foreground-muted tabular-nums">
              {localRerankerPercent}%
            </span>
          </div>
          <p className="text-xs text-foreground-muted mb-3">
            How closely a chunk must match your question before it is cited and sent to the
            model. Same scale as the “% match” shown on each source.
          </p>
          {/* Committed on release, not on every frame: each save rewrites
              data/settings.json and clears the semantic cache server-side. */}
          <input
            id="relevance-threshold"
            type="range"
            min={0}
            max={100}
            step={1}
            value={localRerankerPercent}
            onChange={(e) => setLocalRerankerPercent(Number(e.target.value))}
            onPointerUp={() => setRerankerPercent(localRerankerPercent)}
            onKeyUp={() => setRerankerPercent(localRerankerPercent)}
            className="w-full accent-primary cursor-pointer"
          />
          <p className="text-xs text-foreground-muted/80 mt-3 leading-relaxed">
            <span className="font-medium text-foreground-muted">
              Recommended: {DEFAULT_RELEVANCE_PERCENT}%
            </span>{" "}
            - a deliberately conservative floor, so low-confidence chunks are never fed to
            the model. Much lower and it cited passages the reranker scored at a fraction of
            a percent; at the model’s own boundary (56%) too many questions fell through to
            answering with no citations at all. Raise it to cite only strong matches; 0%
            passes through everything retrieval returned. Applies to your next question - no
            restart needed.
          </p>
        </div>

        {/* Theme */}
        <div className="rounded-xl border border-border bg-surface p-5">
          <p className="text-sm font-semibold text-foreground mb-1">Theme</p>
          <p className="text-xs text-foreground-muted mb-3">
            Defaults to your system preference on first load, then stays where you set it.
          </p>
          <ThemeToggle />
        </div>

        {/* Save */}
        <button
          onClick={handleSave}
          className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary-hover transition-colors"
        >
          <Save className="h-4 w-4" />
          {saved ? "Saved!" : "Save settings"}
        </button>
      </div>
    </div>
  );
}
