"use client";

import { useState, useRef, useEffect } from "react";
import { ChevronDown, Check, X } from "lucide-react";
import { cn } from "@/lib/utils";

export const CURRENT_MODEL = "qwen3";

export function ModelSelector() {
  const [isOpen, setIsOpen] = useState(false);
  const [showComingSoon, setShowComingSoon] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
        setShowComingSoon(false);
      }
    }
    if (isOpen) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  return (
    <div ref={containerRef} className="relative flex-shrink-0">
      <button
        onClick={() => {
          setIsOpen((v) => !v);
          setShowComingSoon(false);
        }}
        className={cn(
          "flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs transition-colors",
          isOpen
            ? "border-primary/60 bg-primary/5 text-foreground"
            : "border-border text-foreground-muted hover:text-foreground hover:border-primary/40"
        )}
      >
        <span className="font-medium">{CURRENT_MODEL}</span>
        <ChevronDown className={cn("h-3 w-3 transition-transform", isOpen && "rotate-180")} />
      </button>

      {isOpen && (
        <div className="absolute bottom-full right-0 mb-2 w-64 rounded-xl border border-border bg-surface-raised shadow-xl z-20 overflow-hidden">
          <div className="p-1.5">
            {/* Current model with checkmark */}
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-primary/5">
              <Check className="h-3.5 w-3.5 text-primary flex-shrink-0" />
              <span className="text-xs font-medium text-foreground">{CURRENT_MODEL}</span>
              <span className="ml-auto text-[10px] text-foreground-muted">local</span>
            </div>

            <div className="my-1.5 border-t border-border" />

            {/* Add model / coming soon */}
            {showComingSoon ? (
              <div className="px-3 py-2">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-xs text-foreground-muted leading-snug">
                    Coming soon — API key support for Claude, GPT-4, and more is on the way.
                  </p>
                  <button
                    onClick={() => setShowComingSoon(false)}
                    className="flex-shrink-0 text-foreground-muted hover:text-foreground transition-colors mt-0.5"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setShowComingSoon(true)}
                className="flex w-full items-center gap-2 px-3 py-2 rounded-lg text-left text-xs text-foreground-muted hover:text-foreground hover:bg-surface transition-colors"
              >
                + Add model
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
