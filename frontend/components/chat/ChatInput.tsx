"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { SendHorizonal, Square } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend: (content: string) => void;
  onStop?: () => void;
  disabled?: boolean;
  isStreaming?: boolean;
  isLoading?: boolean;
}

export function ChatInput({ onSend, onStop, disabled, isStreaming, isLoading }: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "0px";
    const natural = ta.scrollHeight;
    ta.style.height = `${Math.min(Math.max(natural, 44), 200)}px`;
  }, [value]);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [value, onSend]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key !== "Enter") return;
      if (e.metaKey || e.ctrlKey || e.shiftKey) return;
      e.preventDefault();
      handleSend();
    },
    [handleSend]
  );

  return (
    <div className="flex-shrink-0 border-t border-border bg-background px-4 py-3">
      <div className="flex items-end gap-2 rounded-xl border border-border bg-surface focus-within:border-primary/60 focus-within:ring-1 focus-within:ring-ring transition-shadow">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask anything… (Enter to send, ⌘↵ for newline)"
          rows={1}
          style={{ height: "44px" }}
          className="w-full resize-none bg-transparent px-4 py-3 text-sm text-foreground placeholder:text-foreground-muted outline-none overflow-y-auto"
        />
        {isStreaming || isLoading ? (
          <button
            onClick={onStop}
            className="mb-2 mr-2 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-foreground/10 text-foreground hover:bg-foreground/20 transition-colors"
            title="Stop generation"
          >
            <Square className="h-4 w-4 fill-current" />
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!value.trim()}
            className={cn(
              "mb-2 mr-2 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg transition-colors",
              !value.trim()
                ? "text-foreground-muted cursor-not-allowed"
                : "bg-primary text-primary-foreground hover:bg-primary-hover"
            )}
            title="Send (Enter)"
          >
            <SendHorizonal className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  );
}
