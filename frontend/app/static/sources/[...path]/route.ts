import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { Readable } from "node:stream";
import path from "node:path";

/**
 * Serve a stored original out of `data/sources`.
 *
 * This replaces the `frontend/public/static/sources -> ../../../data/sources`
 * symlink, which could not work for the flow the app actually has. Next.js
 * enumerates `public/` **once, at boot**, when not in dev - see
 * `next/dist/server/lib/router-utils/filesystem.js`: the `recursiveReadDir` that
 * fills `publicFolderItems` is inside `if (!opts.dev)`, matching is
 * `items.has(curItemPath)`, and the live filesystem re-check below it is guarded
 * by `opts.dev`. `scripts/start.sh` runs `next build && next start`, so every
 * source ingested *after* the server came up was missing from that snapshot and
 * 404'd: PDFs fell into react-pdf's error slot, text previews painted a red
 * "Preview unavailable", images broke. The normal sequence - start the app, then
 * ingest something, then preview it - hit that path every single time. It only
 * looked verified because testing used files that already existed at boot.
 *
 * A route handler reads the filesystem per request, so it behaves the same in
 * `next dev` and `next start`. Keeping the files off FastAPI is the point of the
 * original decision (`.ai/decisions.md`) and is preserved: these are whole
 * multi-hundred-MB documents, and serving them from the Python process puts them
 * behind the server that has to answer queries.
 *
 * Range requests are implemented because pdf.js relies on them to fetch a large
 * PDF page by page instead of pulling the whole file.
 */

// The route reads whatever is on disk right now; it must never be prerendered
// or cached, or it reintroduces exactly the boot-time snapshot it replaces.
export const dynamic = "force-dynamic";

// `next start` runs with cwd = frontend/, so data/ is one level up. Resolved
// once and used as the containment root for the traversal check below.
const SOURCES_ROOT = path.resolve(process.cwd(), "..", "data", "sources");

// Mirrors _KNOWN_MIME in api/sources.py. A wrong Content-Type is not cosmetic
// here: react-pdf refuses a PDF served as octet-stream, and a text preview
// rendered as a download prompt looks like a broken preview.
const MIME_TYPES: Record<string, string> = {
  ".pdf": "application/pdf",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".tiff": "image/tiff",
  ".txt": "text/plain; charset=utf-8",
  ".md": "text/plain; charset=utf-8",
  ".csv": "text/csv; charset=utf-8",
  ".mp4": "video/mp4",
  ".mov": "video/quicktime",
  ".avi": "video/x-msvideo",
  ".mkv": "video/x-matroska",
  ".webm": "video/webm",
};

export async function GET(
  request: Request,
  ctx: { params: Promise<{ path: string[] }> }
): Promise<Response> {
  const { path: segments } = await ctx.params;

  // Segments arrive percent-encoded - source names are slugs but can carry
  // characters that were escaped by encodeURIComponent on the way out.
  let filePath: string;
  try {
    filePath = path.resolve(SOURCES_ROOT, ...segments.map(decodeURIComponent));
  } catch {
    return new Response("Bad request", { status: 400 });
  }

  // Containment check. `path.resolve` collapses "..", so a request for
  // /static/sources/../../secret would otherwise escape the data directory.
  // The trailing separator stops "/data/sources-private" matching the prefix.
  if (filePath !== SOURCES_ROOT && !filePath.startsWith(SOURCES_ROOT + path.sep)) {
    return new Response("Not found", { status: 404 });
  }

  let size: number;
  try {
    const stats = await stat(filePath);
    if (!stats.isFile()) return new Response("Not found", { status: 404 });
    size = stats.size;
  } catch {
    return new Response("Not found", { status: 404 });
  }

  const contentType =
    MIME_TYPES[path.extname(filePath).toLowerCase()] ?? "application/octet-stream";

  const baseHeaders: Record<string, string> = {
    "Content-Type": contentType,
    // Advertised unconditionally: pdf.js only issues range requests when it
    // sees this on the first response, and without it every preview of a large
    // PDF downloads the whole file before rendering page 1.
    "Accept-Ranges": "bytes",
    // The file at a given URL changes whenever the source is re-ingested, and
    // the name is a stable slug, so a cached copy would show the old document.
    "Cache-Control": "no-store",
  };

  // Only the single-range form is handled - that is all pdf.js sends, and a
  // multipart/byteranges response would need a different body encoding
  // entirely. Anything else falls through to the full-file response, which is
  // always a valid answer to a Range request.
  const rangeHeader = request.headers.get("range");
  const match = rangeHeader?.match(/^bytes=(\d*)-(\d*)$/);

  if (match && size > 0) {
    const [, rawStart, rawEnd] = match;
    let start: number;
    let end: number;

    if (rawStart === "") {
      // Suffix form: "bytes=-500" means the last 500 bytes.
      const suffixLength = Number(rawEnd);
      if (!Number.isFinite(suffixLength) || suffixLength <= 0) {
        return unsatisfiable(size, contentType);
      }
      start = Math.max(0, size - suffixLength);
      end = size - 1;
    } else {
      start = Number(rawStart);
      end = rawEnd === "" ? size - 1 : Number(rawEnd);
    }

    if (!Number.isFinite(start) || !Number.isFinite(end) || start > end || start >= size) {
      return unsatisfiable(size, contentType);
    }
    end = Math.min(end, size - 1);

    // createReadStream's `end` is inclusive, matching HTTP range semantics.
    const stream = Readable.toWeb(
      createReadStream(filePath, { start, end })
    ) as ReadableStream<Uint8Array>;

    return new Response(stream, {
      status: 206,
      headers: {
        ...baseHeaders,
        "Content-Range": `bytes ${start}-${end}/${size}`,
        "Content-Length": String(end - start + 1),
      },
    });
  }

  const stream = Readable.toWeb(createReadStream(filePath)) as ReadableStream<Uint8Array>;
  return new Response(stream, {
    status: 200,
    headers: { ...baseHeaders, "Content-Length": String(size) },
  });
}

function unsatisfiable(size: number, contentType: string): Response {
  return new Response(null, {
    status: 416,
    headers: {
      "Content-Type": contentType,
      "Content-Range": `bytes */${size}`,
      "Accept-Ranges": "bytes",
    },
  });
}
