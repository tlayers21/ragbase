"use client";

import { Document, Page } from "react-pdf";
import { Loader2 } from "lucide-react";
// Imported for its side effect - points pdf.js's shared worker at the local copy
import "@/lib/pdf";

const PAGE_WIDTH = 520;

interface PDFPreviewProps {
  url: string;
}

export default function PDFPreview({ url }: PDFPreviewProps) {
  return (
    <div className="flex justify-center py-2">
      {/* No `options` prop on purpose: react-pdf treats a new options identity as a
          new document, so an inline object here is an infinite reload loop. The only
          entry it ever held was the vendored cMap path, dropped with public/cmaps -
          the corpus is English-only and cMaps are consulted solely for non-Latin
          embedded font encodings. */}
      <Document
        file={url}
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
