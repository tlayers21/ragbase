import { pdfjs } from "react-pdf";

/**
 * The one place pdf.js's worker is configured - `GlobalWorkerOptions` is a
 * singleton, so a second assignment anywhere silently wins.
 *
 * Import for the side effect before rendering a `<Document>`, and use the
 * `pdfjs` re-exported here rather than importing `pdfjs-dist` directly.
 */
pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

export { pdfjs };
