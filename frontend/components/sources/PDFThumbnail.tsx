"use client";

import * as pdfjs from "pdfjs-dist";
import { Document, Page } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

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
