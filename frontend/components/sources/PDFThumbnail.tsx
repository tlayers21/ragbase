"use client";

import { Document, Page } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
// Sets the worker once for every pdf.js consumer - pdfjs-dist is not a direct dep
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
