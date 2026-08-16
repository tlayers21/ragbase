import type { AttachmentType } from "@/types";

// Paste threshold: clipboard text under this length pastes normally into the
// textarea; over this length becomes a text attachment card instead.
export const PASTE_TEXT_THRESHOLD = 5000;

export const ACCEPTED_ATTACHMENT_TYPES =
  "image/png,image/jpeg,image/gif,image/webp,application/pdf,.pdf,.txt,.md,text/plain,text/markdown";

export function classifyFile(file: File): AttachmentType | null {
  if (file.type.startsWith("image/")) return "image";
  const name = file.name.toLowerCase();
  if (file.type === "application/pdf" || name.endsWith(".pdf")) return "pdf";
  if (name.endsWith(".txt") || name.endsWith(".md") || file.type.startsWith("text/")) return "text";
  return null;
}

const PREVIEW_MAX_CHARS = 140;

// First two non-blank lines, additionally capped by character count - pasted
// text is often a single unbroken paragraph with no newlines at all, so the
// line-count cap alone isn't enough to keep the attachment card small.
export function twoLinePreview(text: string): string {
  const lines = text
    .split(/\r?\n/)
    .filter((line) => line.trim().length > 0)
    .slice(0, 2)
    .join("\n");
  return lines.length > PREVIEW_MAX_CHARS ? `${lines.slice(0, PREVIEW_MAX_CHARS)}…` : lines;
}

// Best-effort page count for a PDF attachment card - dynamically imported so
// pdf.js (large) never inflates the main chat bundle for users who never attach
// a PDF. Returns undefined on any failure ("if available" per spec).
export async function getPdfPageCount(file: File): Promise<number | undefined> {
  try {
    // Dynamic so the cost stays off the initial bundle; lib/pdf sets workerSrc
    // to the local worker as a side effect of being imported, which is also
    // what stops this from reaching for a CDN on a machine with no network.
    const { pdfjs } = await import("@/lib/pdf");
    const buf = await file.arrayBuffer();
    const doc = await pdfjs.getDocument({ data: buf }).promise;
    return doc.numPages;
  } catch {
    return undefined;
  }
}
