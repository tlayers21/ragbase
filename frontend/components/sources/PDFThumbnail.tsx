"use client";

import { Document, Page } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
// Sets the worker once, for every pdf.js consumer. Previously this file imported
// `pdfjs-dist` directly and set `workerSrc` itself - which worked only because
// npm hoists react-pdf's copy, since pdfjs-dist is not a declared dependency.
import "@/lib/pdf";

interface PDFThumbnailProps {
  url: string;
}

export default function PDFThumbnail({ url }: PDFThumbnailProps) {
  return (
    <Document file={url} loading="">
      <Page
        pageNumber={1}
        width={130}
        renderTextLayer={false}
        renderAnnotationLayer={false}
      />
    </Document>
  );
}
