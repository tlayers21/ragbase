import type { AttachmentType } from "@/types";

// Clipboard text over this length becomes an attachment card, not a paste
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

// Capped by characters too - pasted text is often one unbroken paragraph
export function twoLinePreview(text: string): string {
  const lines = text
    .split(/\r?\n/)
    .filter((line) => line.trim().length > 0)
    .slice(0, 2)
    .join("\n");
  return lines.length > PREVIEW_MAX_CHARS ? `${lines.slice(0, PREVIEW_MAX_CHARS)}…` : lines;
}

// Best-effort page count, dynamically imported to keep pdf.js out of the chat bundle
export async function getPdfPageCount(file: File): Promise<number | undefined> {
  try {
    // Importing lib/pdf also points workerSrc at the local worker, never a CDN
    const { pdfjs } = await import("@/lib/pdf");
    const buf = await file.arrayBuffer();
    const doc = await pdfjs.getDocument({ data: buf }).promise;
    return doc.numPages;
  } catch {
    return undefined;
  }
}
