"use client";

import { useMemo } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { Loader2 } from "lucide-react";

pdfjs.GlobalWorkerOptions.workerSrc = `https://cdn.jsdelivr.net/npm/pdfjs-dist@5.4.296/build/pdf.worker.min.mjs`;

const PAGE_WIDTH = 520;

interface PDFPreviewProps {
  url: string;
}

export default function PDFPreview({ url }: PDFPreviewProps) {
  const pdfOptions = useMemo(
    () => ({
      cMapUrl: `https://cdn.jsdelivr.net/npm/pdfjs-dist@5.4.296/cmaps/`,
      cMapPacked: true,
    }),
    []
  );

  return (
    <div className="flex justify-center py-2">
      <Document
        file={url}
        options={pdfOptions}
        loading={
          <div className="flex items-center justify-center py-12 text-foreground-muted">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        }
        error={
          <div className="flex items-center justify-center py-12 text-sm text-destructive">
            Preview unavailable
          </div>
        }
      >
        <Page
          pageNumber={1}
          width={PAGE_WIDTH}
          renderTextLayer={false}
          renderAnnotationLayer={false}
        />
      </Document>
    </div>
  );
}
