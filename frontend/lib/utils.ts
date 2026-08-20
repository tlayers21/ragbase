import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function deriveSourceName(filename: string): string {
  return filename
    .replace(/\.[^/.]+$/, "")
    .toLowerCase()
    .replace(/\s+/g, "_");
}

const IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".webp", ".tiff"]);

// Formats whose bytes are meaningful as characters, unlike the office containers
const TEXT_EXTENSIONS = new Set([".txt", ".md", ".csv"]);

/**
 * Decide how to preview a stored source from its extension alone.
 *
 * `"binary"` is a real kind, not a fallback: office and video containers must
 * never resolve to "text", which would fetch a 300MB file to render mojibake.
 */
export function sourceTypeFromExt(fileExt: string): "pdf" | "image" | "text" | "binary" {
  const ext = fileExt.toLowerCase();
  if (ext === ".pdf") return "pdf";
  if (IMAGE_EXTENSIONS.has(ext)) return "image";
  if (TEXT_EXTENSIONS.has(ext)) return "text";
  return "binary";
}

// An explicit list because slugs can contain dots, so a greedy regex eats the name
const SOURCE_EXTENSION_RE =
  /\.(pdf|docx?|pptx?|xlsx?|txt|md|csv|epub|rtf|odt|odp|ods|png|jpe?g|webp|tiff|mp4|mov|mkv|webm|avi)$/i;

/**
 * Turn a stored source slug back into a readable title.
 *
 * An already-uppercase word is left alone rather than lowercased into "Pdf".
 */
export function humanizeSourceName(source: string): string {
  const spaced = source
    .replace(SOURCE_EXTENSION_RE, "")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!spaced) return source;
  return spaced
    .split(" ")
    .map((word) =>
      word === word.toUpperCase() ? word : word.charAt(0).toUpperCase() + word.slice(1)
    )
    .join(" ");
}

// Linear, not sigmoid - a sigmoid saturates across most of the reranker's real range
export function relevancePercent(score: number): number {
  return Math.round(Math.max(0, Math.min(100, ((score + 10) / 18) * 100)));
}

// The inverse for the settings slider - not exact at the ends, where the display clamps
export function scoreFromRelevancePercent(percent: number): number {
  return (percent / 100) * 18 - 10;
}
