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

/**
 * Decide how to preview a stored source from its extension alone.
 *
 * The extension now arrives with the source listing (`SourceSummary.file_ext`),
 * which is what lets previews skip the HEAD against `/sources/{source}/file`
 * that used to sniff Content-Type — one fewer FastAPI round-trip per card.
 * Anything unrecognized renders as text, matching the old server-side default.
 */
export function sourceTypeFromExt(fileExt: string): "pdf" | "image" | "text" {
  const ext = fileExt.toLowerCase();
  if (ext === ".pdf") return "pdf";
  if (IMAGE_EXTENSIONS.has(ext)) return "image";
  return "text";
}

// Extensions we're willing to strip off a source name. Deliberately an explicit
// list: source slugs can legitimately contain dots (e.g. "notes_v1.2"), so a
// greedy /\.[^.]+$/ would eat part of the name.
const SOURCE_EXTENSION_RE =
  /\.(pdf|docx?|pptx?|xlsx?|txt|md|csv|epub|rtf|odt|odp|ods|png|jpe?g|webp|tiff|mp4|mov|mkv|webm|avi)$/i;

/**
 * Turn a stored source name into something readable.
 *
 * Sources are slugs produced by `deriveSourceName` (lowercased, spaces → "_"),
 * so "applied_combinatorics" has to come back out as "Applied Combinatorics".
 * An already-uppercase word (an acronym like "PDF" from an original filename)
 * is left alone rather than being lowercased into "Pdf".
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

// BGE-Reranker-v2-m3 emits raw, unbounded logits (roughly -10..+8), not
// probabilities — multiplying one by 100 yields nonsense like "-399% match".
//
// A sigmoid was the obvious normalization but is wrong for display here: it
// saturates near 0 across most of the reranker's actual output range, so a
// clearly relevant chunk scoring -5 rendered as "1% match" and anything at or
// near the -8.0 RERANKER_MIN_SCORE cutoff showed a flat 0%. Mapping the -10..+8
// range linearly instead spreads the scores the UI actually sees: -8 (the
// minimum any displayed chunk can have) → 11%, 0 → 56%, +8 → 100%.
export function relevancePercent(score: number): number {
  return Math.round(Math.max(0, Math.min(100, ((score + 10) / 18) * 100)));
}
