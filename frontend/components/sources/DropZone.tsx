"use client";

import { useState, useCallback, useRef } from "react";
import { Upload, FolderOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { ACCEPTED_INGEST_TYPES } from "@/lib/config";

interface DropZoneProps {
  onDrop: (files: File[], describeImages: boolean) => void;
  isUploading: boolean;
}

export function DropZone({ onDrop, isUploading }: DropZoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  // Off by default - figure description adds a Docling pass on top of anydoc
  const [describeImages, setDescribeImages] = useState(false);
  const dragCounterRef = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;
      onDrop(Array.from(files), describeImages);
    },
    [onDrop, describeImages]
  );

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current++;
    setIsDragging(true);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current--;
    if (dragCounterRef.current === 0) setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounterRef.current = 0;
      setIsDragging(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles]
  );

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={cn(
        "mx-3 mb-3 rounded-xl border-2 border-dashed p-4 text-center transition-colors",
        isDragging
          ? "border-primary bg-primary/5 text-primary"
          : "border-border text-foreground-muted hover:border-primary/40 hover:text-foreground"
      )}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPTED_INGEST_TYPES}
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
        disabled={isUploading}
      />

      {isUploading ? (
        <div className="flex flex-col items-center gap-2">
          <div className="flex gap-1">
            <span className="loading-dot h-1.5 w-1.5 rounded-full bg-primary" />
            <span className="loading-dot h-1.5 w-1.5 rounded-full bg-primary" />
            <span className="loading-dot h-1.5 w-1.5 rounded-full bg-primary" />
          </div>
          <p className="text-[11px] text-primary">Uploading…</p>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2">
          <Upload className="h-5 w-5" />
          <p className="text-[11px] font-medium">Drop files to ingest</p>
          <button
            onClick={() => inputRef.current?.click()}
            className="flex items-center gap-1 text-[10px] underline underline-offset-2 hover:text-primary transition-colors"
          >
            <FolderOpen className="h-3 w-3" />
            Browse files
          </button>

          <label className="mt-1 flex cursor-pointer items-center gap-1.5 text-[10px] text-foreground-muted hover:text-foreground transition-colors">
            <input
              type="checkbox"
              checked={describeImages}
              onChange={(e) => setDescribeImages(e.target.checked)}
              className="h-3 w-3 cursor-pointer accent-primary"
            />
            Describe diagrams (slower, PDFs only)
          </label>
        </div>
      )}
    </div>
  );
}
