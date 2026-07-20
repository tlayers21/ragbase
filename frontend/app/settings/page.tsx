"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Save } from "lucide-react";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { useSettings } from "@/hooks/useSettings";

export default function SettingsPage() {
  const { userId, setUserId, apiUrl, setApiUrl } = useSettings();
  const [localUserId, setLocalUserId] = useState(userId);
  const [localApiUrl, setLocalApiUrl] = useState(apiUrl);
  const [saved, setSaved] = useState(false);

  function handleSave() {
    setUserId(localUserId.trim() || "test_user");
    setApiUrl(localApiUrl.trim() || "http://localhost:8001");
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
        {/* User ID */}
        <div className="rounded-xl border border-border bg-surface p-5">
          <label className="block text-sm font-semibold text-foreground mb-1">
            User ID
          </label>
          <p className="text-xs text-foreground-muted mb-3">
            Used to isolate your documents and sessions. Changing this switches
            to a different knowledge base.
          </p>
          <input
            type="text"
            value={localUserId}
            onChange={(e) => setLocalUserId(e.target.value)}
            placeholder="test_user"
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
            <code className="font-mono text-primary">http://localhost:8001</code>.
          </p>
          <input
            type="url"
            value={localApiUrl}
            onChange={(e) => setLocalApiUrl(e.target.value)}
            placeholder="http://localhost:8001"
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-foreground-muted outline-none focus:border-primary/60 focus:ring-1 focus:ring-ring transition-shadow"
          />
        </div>

        {/* Theme */}
        <div className="rounded-xl border border-border bg-surface p-5">
          <p className="text-sm font-semibold text-foreground mb-1">Theme</p>
          <p className="text-xs text-foreground-muted mb-3">
            Defaults to your system preference.
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
