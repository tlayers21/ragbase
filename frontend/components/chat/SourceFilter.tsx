"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { ChevronDown, Search, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SourceSummary } from "@/types";

interface SourceFilterProps {
  sources: SourceSummary[];
  selectedSources: Set<string>;
  rightSlot?: React.ReactNode;
  onToggle: (source: string) => void;
  onSelectAll: () => void;
  onClearAll: () => void;
}

export function SourceFilter({
  sources,
  selectedSources,
  rightSlot,
  onToggle,
  onSelectAll,
  onClearAll,
}: SourceFilterProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    if (isOpen) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  const filtered = useMemo(
    () => sources.filter((s) => s.source.toLowerCase().includes(search.toLowerCase())),
    [sources, search]
  );

  // Always render — show a placeholder when no sources exist
  if (sources.length === 0) {
    return (
      <div className="px-4 py-2 border-t border-border bg-background flex-shrink-0 flex items-center justify-between gap-2">
        <span className="text-xs text-foreground-muted/60 italic">No sources ingested yet</span>
        {rightSlot}
      </div>
    );
  }

  const isAllSelected = selectedSources.size === sources.length;
  const label = isAllSelected
    ? "All sources"
    : `${selectedSources.size}/${sources.length} selected`;

  return (
    <div
      ref={containerRef}
      className="relative px-4 py-2 border-t border-border bg-background flex-shrink-0 flex items-center gap-2"
    >
      <button
        onClick={() => setIsOpen((v) => !v)}
        className={cn(
          "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors",
          isAllSelected
            ? "border-border text-foreground-muted hover:text-foreground"
            : "border-primary/60 bg-primary/10 text-primary"
        )}
      >
        {label}
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", isOpen && "rotate-180")} />
      </button>
      {rightSlot && <div className="ml-auto">{rightSlot}</div>}

      {isOpen && (
        <div className="absolute bottom-full left-4 mb-2 w-72 rounded-xl border border-border bg-surface-raised shadow-xl z-20 overflow-hidden">
          {/* Search */}
          <div className="p-2 border-b border-border">
            <div className="flex items-center gap-2 rounded-lg border border-border bg-background px-2 py-1.5">
              <Search className="h-3.5 w-3.5 text-foreground-muted flex-shrink-0" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search sources…"
                className="flex-1 bg-transparent text-xs text-foreground placeholder:text-foreground-muted outline-none"
                autoFocus
              />
            </div>
          </div>

          {/* Select all / Clear all */}
          <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border">
            <button
              onClick={onSelectAll}
              className="text-[11px] font-medium text-primary hover:underline"
            >
              Select all
            </button>
            <span className="text-border">·</span>
            <button
              onClick={onClearAll}
              className="text-[11px] font-medium text-foreground-muted hover:text-foreground hover:underline"
            >
              Clear all
            </button>
          </div>

          {/* List */}
          <div className="max-h-64 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <p className="px-3 py-4 text-center text-xs text-foreground-muted">No matches</p>
            ) : (
              filtered.map((s) => {
                const checked = selectedSources.has(s.source);
                return (
                  <button
                    key={s.source}
                    onClick={() => onToggle(s.source)}
                    className={cn(
                      "flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors hover:bg-surface",
                      checked ? "text-foreground" : "text-foreground-muted"
                    )}
                  >
                    <Check
                      className={cn(
                        "h-3.5 w-3.5 flex-shrink-0 transition-opacity",
                        checked ? "text-primary opacity-100" : "opacity-0"
                      )}
                    />
                    <span className="flex-1 truncate text-xs">{s.source}</span>
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
