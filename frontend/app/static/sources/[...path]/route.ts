import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { Readable } from "node:stream";
import path from "node:path";

/**
 * Serve a stored original out of `data/sources`, reading the disk per request.
 *
 * A route handler rather than a `public/` mount, which Next enumerates once at
 * boot; range requests are implemented because pdf.js needs them.
 */

// Never prerender or cache - that reintroduces the boot-time snapshot this replaces
export const dynamic = "force-dynamic";

// cwd is frontend/ under `next start`, so data/ is one level up
const SOURCES_ROOT = path.resolve(process.cwd(), "..", "data", "sources");

// Mirrors _KNOWN_MIME - react-pdf refuses a PDF served as octet-stream
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

  // Segments arrive percent-encoded from encodeURIComponent
  let filePath: string;
  try {
    filePath = path.resolve(SOURCES_ROOT, ...segments.map(decodeURIComponent));
  } catch {
    return new Response("Bad request", { status: 400 });
  }

  // Containment check - the trailing separator stops "sources-private" matching
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
    // Unconditional - pdf.js only sends ranges after seeing this on the first response
    "Accept-Ranges": "bytes",
    // The slug is stable across re-ingest, so a cached copy shows the old document
    "Cache-Control": "no-store",
  };

  // Single-range only; anything else falls through to the full file, still valid
  const rangeHeader = request.headers.get("range");
  const match = rangeHeader?.match(/^bytes=(\d*)-(\d*)$/);

  if (match && size > 0) {
    const [, rawStart, rawEnd] = match;
    let start: number;
    let end: number;

    if (rawStart === "") {
      // Suffix form: "bytes=-500" means the last 500 bytes
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

    // createReadStream's `end` is inclusive, matching HTTP range semantics
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
