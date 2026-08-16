import { pdfjs } from "react-pdf";

/**
 * The one place pdf.js's worker is configured.
 *
 * `GlobalWorkerOptions` is a singleton on the pdfjs-dist module, and react-pdf
 * 10.4.1 pins pdfjs-dist to exactly 5.4.296 so npm hoists a single copy — which
 * means every module that assigned `workerSrc` at import time was writing to the
 * *same* object, and whichever loaded last won. `PDFPreview` pointed it at
 * jsDelivr while `PDFThumbnail` pointed it at the local file, so opening one
 * preview silently switched the thumbnails onto the CDN worker too.
 *
 * The CDN was the real problem: RAGbase's premise is that everything runs
 * locally with no network (`.ai/instructions.md` §1), and a PDF preview that
 * needs cdn.jsdelivr.net fails on exactly the machine the app is built for. The
 * worker in `public/` is byte-identical to the installed one — both md5
 * daf3628f39bb3fd351408e2d4336ee58 — so this is the same code, served from
 * ourselves.
 *
 * It also removes the version string that used to be hardcoded in three places
 * against a floating `^10.4.1`: nothing here names a version, so a react-pdf
 * bump can no longer leave a worker/library mismatch behind.
 *
 * Import this module for its side effect before rendering any `<Document>`, and
 * use the `pdfjs` it re-exports (react-pdf's own instance) rather than importing
 * `pdfjs-dist` directly — `PDFThumbnail` did the latter even though pdfjs-dist
 * is not a declared dependency, so it resolved only by hoisting.
 */
pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

export { pdfjs };
