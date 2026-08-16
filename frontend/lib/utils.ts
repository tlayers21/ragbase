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

// Formats whose bytes are meaningful as characters. Everything else that the
// ingest surface accepts - the 20 office formats, e-books, video - is a
// container we have no renderer for.
const TEXT_EXTENSIONS = new Set([".txt", ".md", ".csv"]);

/**
 * Decide how to preview a stored source from its extension alone.
 *
 * The extension arrives with the source listing (`SourceSummary.file_ext`),
 * which is what lets previews skip the HEAD against `/sources/{source}/file`
 * that used to sniff Content-Type - one fewer FastAPI round-trip per card.
 *
 * The fourth kind, `"binary"`, exists because this used to end in a bare
 * `return "text"`. `SUPPORTED_EXTENSIONS` on the backend covers 20 office
 * formats plus five video containers, so `.docx`, `.pptx`, `.xlsx`, `.epub` and
 * `.mp4` all resolved to "text" - and the preview pane then fetched the file and
 * dumped 800 characters of ZIP or OLE header into a `<pre>`. For a video it was
 * worse than cosmetic: `fetchTextFile` downloads the response in full and calls
 * `.text()` on it *before* the slice, so previewing a 300MB .mp4 pulled the
 * whole thing into memory to render mojibake.
 */
export function sourceTypeFromExt(fileExt: string): "pdf" | "image" | "text" | "binary" {
  const ext = fileExt.toLowerCase();
  if (ext === ".pdf") return "pdf";
  if (IMAGE_EXTENSIONS.has(ext)) return "image";
  if (TEXT_EXTENSIONS.has(ext)) return "text";
  return "binary";
}

// Extensions we're willing to strip off a source name. Deliberately an explicit
// list: source slugs can legitimately contain dots (e.g. "notes_v1.2"), so a
// greedy /\.[^.]+$/ would eat part of the name.
const SOURCE_EXTENSION_RE =
  /\.(pdf|docx?|pptx?|xlsx?|txt|md|csv|epub|rtf|odt|odp|ods|png|jpe?g|webp|tiff|mp4|mov|mkv|webm|avi)$/i;

/**
 * Turn a stored source name into something readable.
 *
 * Sources are slugs produced by `deriveSourceName` (lowercased, spaces -> "_"),
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
// probabilities - multiplying one by 100 yields nonsense like "-399% match".
//
// A sigmoid was the obvious normalization but is wrong for display here: it
// saturates near 0 across most of the reranker's actual output range, so a
// clearly relevant chunk scoring -5 rendered as "1% match" and anything at or
// near the -8.0 RERANKER_MIN_SCORE cutoff showed a flat 0%. Mapping the -10..+8
// range linearly instead spreads the scores the UI actually sees: -8 (the
// minimum any displayed chunk can have) -> 11%, 0 -> 56%, +8 -> 100%.
export function relevancePercent(score: number): number {
  return Math.round(Math.max(0, Math.min(100, ((score + 10) / 18) * 100)));
}

// The inverse, for the settings threshold slider: the user picks a percentage on
// the same scale the match badges use, and the backend wants the raw logit.
// Anchors: 0% -> -10.0, 44% -> -2.08 (the shipped default floor), 100% -> +8.0.
//
// Not a true inverse at the ends, because relevancePercent clamps - every score
// at or below -10 displays as 0%. That only matters in the direction that's
// harmless here: 0% asks for everything, and the backend treats a floor at the
// bottom of the scale as exactly that (see rerank_candidates).
export function scoreFromRelevancePercent(percent: number): number {
  return (percent / 100) * 18 - 10;
}
