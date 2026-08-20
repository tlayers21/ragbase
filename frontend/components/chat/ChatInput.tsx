"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { v4 as uuid } from "uuid";
import { SendHorizonal, Square, Paperclip, X, FileText, AlignLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  ACCEPTED_ATTACHMENT_TYPES,
  PASTE_TEXT_THRESHOLD,
  classifyFile,
  getPdfPageCount,
  twoLinePreview,
} from "@/lib/attachments";
import type { PendingAttachment } from "@/types";

const MIN_HEIGHT = 36;
const MAX_HEIGHT = 220;

interface ChatInputProps {
  onSend: (content: string, attachments: PendingAttachment[]) => void;
  onStop?: () => void;
  isStreaming?: boolean;
  isLoading?: boolean;
}

function PendingAttachmentCard({
  attachment,
  onRemove,
}: {
  attachment: PendingAttachment;
  onRemove: () => void;
}) {
  const isPasted = attachment.name === "Pasted text";
  const textLabel = isPasted
    ? `Pasted text (${attachment.charCount ?? 0} chars)`
    : `${attachment.name} (${attachment.charCount ?? 0} chars)`;

  return (
    <div className="relative flex max-w-[220px] items-start gap-2 rounded-lg border border-border bg-background px-2 py-1.5">
      {attachment.type === "image" ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={attachment.previewUrl}
          alt=""
          className="h-9 w-9 flex-shrink-0 rounded object-cover"
        />
      ) : attachment.type === "pdf" ? (
        <FileText className="h-5 w-5 flex-shrink-0 text-foreground-muted" />
      ) : (
        <AlignLeft className="h-5 w-5 flex-shrink-0 text-foreground-muted" />
      )}

      <div className="min-w-0 flex-1 pt-0.5">
        <p className="truncate text-xs font-medium text-foreground">
          {attachment.type === "image" ? attachment.name || "Pasted image" : null}
          {attachment.type === "pdf" ? attachment.name : null}
          {attachment.type === "text" ? textLabel : null}
        </p>
        {attachment.type === "pdf" && (
          <p className="text-[10px] text-foreground-muted">
            {attachment.pageCount
              ? `${attachment.pageCount} page${attachment.pageCount === 1 ? "" : "s"}`
              : "PDF"}
          </p>
        )}
        {attachment.type === "text" && attachment.preview && (
          <p className="line-clamp-2 overflow-hidden text-[10px] text-foreground-muted whitespace-pre-line break-all">
            {attachment.preview}
          </p>
        )}
      </div>

      <button
        type="button"
        onClick={onRemove}
        className="flex-shrink-0 rounded p-0.5 text-foreground-muted hover:text-foreground focus:outline-none"
        title="Remove attachment"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}

export function ChatInput({ onSend, onStop, isStreaming, isLoading }: ChatInputProps) {
  const [value, setValue] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "0px";
    const natural = ta.scrollHeight;
    ta.style.height = `${Math.min(Math.max(natural, MIN_HEIGHT), MAX_HEIGHT)}px`;
  }, [value]);

  const addImageAttachment = useCallback((file: File, name: string) => {
    const previewUrl = URL.createObjectURL(file);
    setAttachments((prev) => [
      ...prev,
      { id: uuid(), type: "image", name, file, previewUrl },
    ]);
  }, []);

  const addTextAttachment = useCallback((name: string, text: string) => {
    setAttachments((prev) => [
      ...prev,
      { id: uuid(), type: "text", name, text, charCount: text.length, preview: twoLinePreview(text) },
    ]);
  }, []);

  const handleFiles = useCallback(
    (files: FileList | File[]) => {
      Array.from(files).forEach((file) => {
        const kind = classifyFile(file);
        if (!kind) return;

        if (kind === "image") {
          addImageAttachment(file, file.name);
        } else if (kind === "pdf") {
          const id = uuid();
          setAttachments((prev) => [...prev, { id, type: "pdf", name: file.name, file }]);
          getPdfPageCount(file).then((pageCount) => {
            if (pageCount === undefined) return;
            setAttachments((prev) =>
              prev.map((a) => (a.id === id ? { ...a, pageCount } : a))
            );
          });
        } else {
          file.text().then((text) => addTextAttachment(file.name, text));
        }
      });
    },
    [addImageAttachment, addTextAttachment]
  );

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => {
      const target = prev.find((a) => a.id === id);
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((a) => a.id !== id);
    });
  }, []);

  const handlePaste = useCallback(
    (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      const items = e.clipboardData?.items;
      if (items) {
        for (const item of Array.from(items)) {
          if (item.type.startsWith("image/")) {
            const blob = item.getAsFile();
            if (blob) {
              e.preventDefault();
              addImageAttachment(blob, "Pasted image");
            }
            return;
          }
        }
      }

      const text = e.clipboardData?.getData("text/plain") ?? "";
      if (text.length > PASTE_TEXT_THRESHOLD) {
        e.preventDefault();
        addTextAttachment("Pasted text", text);
      }
      // Otherwise: let the browser paste normally into the textarea
    },
    [addImageAttachment, addTextAttachment]
  );

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed && attachments.length === 0) return;
    const questionText = trimmed || "What can you tell me about the attached content?";
    onSend(questionText, attachments);
    setValue("");
    setAttachments([]);
    if (textareaRef.current) {
      textareaRef.current.style.height = `${MIN_HEIGHT}px`;
    }
  }, [value, attachments, onSend]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key !== "Enter") return;
      if (e.metaKey || e.ctrlKey || e.shiftKey) return;
      e.preventDefault();
      handleSend();
    },
    [handleSend]
  );

  const canSend = value.trim().length > 0 || attachments.length > 0;

  return (
    <div className="flex-shrink-0 border-t border-border bg-background px-4 py-3">
      <div className="flex flex-col rounded-xl border border-border bg-surface focus-within:border-border/80 transition-shadow">
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-2 px-3 pt-3">
            {attachments.map((a) => (
              <PendingAttachmentCard
                key={a.id}
                attachment={a}
                onRemove={() => removeAttachment(a.id)}
              />
            ))}
          </div>
        )}

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder="Ask anything…"
          rows={1}
          style={{ height: `${MIN_HEIGHT}px` }}
          className="w-full resize-none bg-transparent px-4 pt-2 pb-1 text-sm text-foreground placeholder:text-foreground-muted outline-none overflow-y-auto"
        />

        <div className="flex items-center justify-between px-2 pb-1">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg text-foreground-muted hover:text-foreground hover:bg-foreground/10 transition-colors focus:outline-none"
            title="Attach files"
          >
            <Paperclip className="h-4 w-4" />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_ATTACHMENT_TYPES}
            className="hidden"
            onChange={(e) => {
              if (e.target.files) handleFiles(e.target.files);
              e.target.value = "";
            }}
          />

          {isStreaming || isLoading ? (
            <button
              onClick={onStop}
              className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-foreground/10 text-foreground hover:bg-foreground/20 transition-colors focus:outline-none"
              title="Stop generation"
            >
              <Square className="h-4 w-4 fill-current" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!canSend}
              className={cn(
                "flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg transition-colors focus:outline-none",
                !canSend
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
    </div>
  );
}
