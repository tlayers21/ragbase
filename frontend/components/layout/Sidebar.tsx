"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import {
  Plus,
  MessageSquare,
  Settings,
  ChevronLeft,
  ChevronRight,
  MoreHorizontal,
  Pencil,
  Pin,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useSettings } from "@/hooks/useSettings";
import { HISTORY_TOKEN_BUDGET } from "@/lib/config";
import type { ChatSession } from "@/types";

function formatK(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

interface SidebarProps {
  sessions: ChatSession[];
  activeSessionId: string | null;
  estimatedTokens?: number;
  onNewSession: () => void;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  onRenameSession: (id: string, title: string) => void;
  onPinSession: (id: string, pinned: boolean) => void;
  onToggleCollapse: () => void;
}

function formatTime(ts: number): string {
  const d = new Date(ts);
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - d.getTime()) / 86_400_000);
  if (diffDays === 0) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return d.toLocaleDateString([], { weekday: "short" });
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function Sidebar({
  sessions,
  activeSessionId,
  estimatedTokens = 0,
  onNewSession,
  onSelectSession,
  onDeleteSession,
  onRenameSession,
  onPinSession,
  onToggleCollapse,
}: SidebarProps) {
  const { displayName } = useSettings();
  const sorted = [...sessions].sort((a, b) => b.updatedAt - a.updatedAt);
  const pinnedSessions = sorted.filter((s) => s.pinned);
  const recentSessions = sorted.filter((s) => !s.pinned);

  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const skipNextCommitRef = useRef(false);

  // Close dropdown when clicking anywhere outside
  useEffect(() => {
    if (!openMenuId) return;
    function handleClick() {
      setOpenMenuId(null);
    }
    document.addEventListener("click", handleClick);
    return () => document.removeEventListener("click", handleClick);
  }, [openMenuId]);

  useEffect(() => {
    if (editingId) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editingId]);

  function startEditing(session: ChatSession) {
    setOpenMenuId(null);
    setEditingId(session.id);
    setDraftTitle(session.title);
  }

  function commitEdit() {
    if (skipNextCommitRef.current) {
      skipNextCommitRef.current = false;
      setEditingId(null);
      return;
    }
    if (editingId) {
      const trimmed = draftTitle.trim();
      if (trimmed) onRenameSession(editingId, trimmed);
    }
    setEditingId(null);
  }

  function cancelEdit() {
    skipNextCommitRef.current = true;
    setEditingId(null);
  }

  function handleMenuToggle(e: React.MouseEvent, sessionId: string) {
    e.stopPropagation();
    setOpenMenuId((prev) => (prev === sessionId ? null : sessionId));
  }

  function handlePin(session: ChatSession) {
    setOpenMenuId(null);
    onPinSession(session.id, !session.pinned);
  }

  function handleDelete(id: string) {
    setOpenMenuId(null);
    setPendingDeleteId(id);
  }

  const renderSession = (session: ChatSession) => {
    const isActive = session.id === activeSessionId;
    const isEditing = editingId === session.id;
    const isMenuOpen = openMenuId === session.id;

    return (
      <div
        key={session.id}
        className={cn(
          "group relative flex items-center gap-2 rounded-lg px-2 py-2 mb-0.5 cursor-pointer transition-colors",
          isActive
            ? "bg-sidebar-item-active text-sidebar-item-active-text"
            : "text-foreground hover:bg-sidebar-item-hover"
        )}
        onClick={() => !isEditing && onSelectSession(session.id)}
      >
        <MessageSquare className="h-3.5 w-3.5 flex-shrink-0 opacity-60" />
        <div className="flex-1 min-w-0">
          {isEditing ? (
            <input
              ref={inputRef}
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              onBlur={commitEdit}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commitEdit();
                } else if (e.key === "Escape") {
                  e.preventDefault();
                  cancelEdit();
                }
              }}
              className="w-full bg-transparent border-b border-current text-xs font-medium text-foreground outline-none"
            />
          ) : (
            <p className="truncate text-xs font-medium">{session.title}</p>
          )}
          <p className="text-[10px] opacity-50">{formatTime(session.updatedAt)}</p>
        </div>

        {/* 3-dots menu trigger */}
        {!isEditing && (
          <div className="relative flex-shrink-0">
            <button
              onClick={(e) => handleMenuToggle(e, session.id)}
              className={cn(
                "rounded p-0.5 transition-opacity",
                isMenuOpen
                  ? "opacity-100 text-foreground"
                  : "opacity-0 group-hover:opacity-100 text-foreground-muted hover:text-foreground"
              )}
              title="More options"
            >
              <MoreHorizontal className="h-3.5 w-3.5" />
            </button>

            {/* Dropdown menu */}
            {isMenuOpen && (
              <div
                className="absolute right-0 top-6 z-20 w-36 rounded-lg border border-border bg-surface-raised shadow-xl py-1"
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  onClick={() => startEditing(session)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-foreground hover:bg-sidebar-item-hover transition-colors"
                >
                  <Pencil className="h-3 w-3 flex-shrink-0" />
                  Rename
                </button>
                <button
                  onClick={() => handlePin(session)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-foreground hover:bg-sidebar-item-hover transition-colors"
                >
                  <Pin className="h-3 w-3 flex-shrink-0" />
                  {session.pinned ? "Unpin" : "Pin"}
                </button>
                <div className="border-t border-border my-1" />
                <button
                  onClick={() => handleDelete(session.id)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-destructive hover:bg-sidebar-item-hover transition-colors"
                >
                  <Trash2 className="h-3 w-3 flex-shrink-0" />
                  Delete
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <aside className="flex h-full w-64 flex-shrink-0 flex-col bg-sidebar-bg border-r border-sidebar-border">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-sidebar-border">
        <div className="flex items-center gap-2">
          <img src="/logo.png" alt="RAGbase" style={{ width: 36, height: 36, display: 'block' }} />
          <span className="font-semibold text-sm text-foreground">RAGbase</span>
        </div>
        <button
          onClick={onToggleCollapse}
          className="rounded p-1 text-foreground-muted hover:text-foreground transition-colors"
          title="Collapse sidebar"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* New chat button */}
      <div className="px-3 pt-3 pb-1">
        <button
          onClick={onNewSession}
          className="flex w-full items-center gap-2 rounded-lg border border-border bg-surface-raised px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-sidebar-item-hover"
        >
          <Plus className="h-4 w-4" />
          New chat
        </button>
      </div>

      {/* Session list */}
      <nav className="flex-1 overflow-y-auto px-2 py-1">
        {sorted.length === 0 ? (
          <p className="px-2 py-4 text-center text-xs text-foreground-muted">No chats yet</p>
        ) : (
          <>
            {pinnedSessions.length > 0 && (
              <>
                <p className="px-2 py-1 text-[10px] font-medium uppercase tracking-wider text-foreground-muted/60">
                  Pinned
                </p>
                {pinnedSessions.map(renderSession)}
                {recentSessions.length > 0 && (
                  <p className="px-2 pt-2 pb-1 text-[10px] font-medium uppercase tracking-wider text-foreground-muted/60">
                    Recents
                  </p>
                )}
              </>
            )}
            {recentSessions.map(renderSession)}
          </>
        )}
      </nav>

      {/* Footer */}
      <div className="border-t border-sidebar-border px-3 pt-2 pb-1">
        {displayName && (
          <p className="px-2 pb-1 text-xs text-foreground-muted/70">Hey, {displayName}</p>
        )}
        {estimatedTokens > 0 && (() => {
          const pct = estimatedTokens / HISTORY_TOKEN_BUDGET;
          const barColor =
            pct >= 0.9 ? "bg-red-500" : pct >= 0.75 ? "bg-amber-500" : "bg-green-500";
          return (
            <div className="px-2 pb-2">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] text-foreground-muted/60">Context</span>
                <span className="text-[10px] tabular-nums text-foreground-muted/60">
                  {formatK(estimatedTokens)} / {formatK(HISTORY_TOKEN_BUDGET)}
                </span>
              </div>
              <div className="h-1 w-full rounded-full bg-border overflow-hidden">
                <div
                  className={cn("h-full rounded-full transition-all duration-500", barColor)}
                  style={{ width: `${Math.min(100, pct * 100).toFixed(1)}%` }}
                />
              </div>
            </div>
          );
        })()}
        <Link
          href="/settings"
          className="flex items-center gap-2 rounded-lg px-2 py-2 text-xs text-foreground-muted hover:text-foreground hover:bg-sidebar-item-hover transition-colors"
        >
          <Settings className="h-4 w-4" />
          Settings
        </Link>
      </div>

      <ConfirmDialog
        isOpen={pendingDeleteId !== null}
        title="Delete this chat?"
        description="This cannot be undone."
        confirmLabel="Delete"
        destructive
        onConfirm={() => {
          if (pendingDeleteId) onDeleteSession(pendingDeleteId);
          setPendingDeleteId(null);
        }}
        onCancel={() => setPendingDeleteId(null)}
      />
    </aside>
  );
}

// Floating button shown in place of the sidebar when it's collapsed.
export function SidebarToggle({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="fixed left-4 top-1/2 -translate-y-1/2 z-10 flex flex-col items-center gap-1 rounded-r-lg border border-l-0 border-border bg-surface px-2 py-3 text-foreground-muted hover:text-foreground transition-colors shadow-sm"
      title="Show sidebar"
    >
      <ChevronRight className="h-4 w-4" />
    </button>
  );
}
