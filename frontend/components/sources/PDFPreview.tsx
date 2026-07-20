"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

const PAGE_WIDTH = 520;
// A4 aspect ratio placeholder height — replaced once the page renders
const EST_PAGE_HEIGHT = Math.round(PAGE_WIDTH * 1.414);

function LazyPage({
  pageNumber,
  onVisible,
}: {
  pageNumber: number;
  onVisible: (page: number, visible: boolean) => void;
}) {
  const [shouldRender, setShouldRender] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) setShouldRender(true);
        onVisible(pageNumber, entry.isIntersecting);
      },
      { threshold: 0.05 }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [pageNumber, onVisible]);

  return (
    <div ref={ref}>
      {shouldRender ? (
        <Page
          pageNumber={pageNumber}
          width={PAGE_WIDTH}
          renderTextLayer
          renderAnnotationLayer
        />
      ) : (
        <div
          style={{ width: PAGE_WIDTH, height: EST_PAGE_HEIGHT }}
          className="rounded bg-surface animate-pulse"
        />
      )}
    </div>
  );
}

interface PDFPreviewProps {
  url: string;
}

export default function PDFPreview({ url }: PDFPreviewProps) {
  const [numPages, setNumPages] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const visibleRef = useRef<Set<number>>(new Set());

  const onDocumentLoadSuccess = useCallback(({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
    setCurrentPage(1);
    visibleRef.current.clear();
  }, []);

  const handlePageVisible = useCallback((page: number, visible: boolean) => {
    if (visible) {
      visibleRef.current.add(page);
    } else {
      visibleRef.current.delete(page);
    }
    const sorted = Array.from(visibleRef.current).sort((a, b) => a - b);
    if (sorted.length > 0) setCurrentPage(sorted[0]);
  }, []);

  return (
    <div className="flex flex-col gap-2 py-2">
      {numPages > 1 && (
        <div className="flex justify-center">
          <span className="text-[10px] tabular-nums text-foreground-muted">
            Page {currentPage} of {numPages}
          </span>
        </div>
      )}
      <Document
        file={url}
        onLoadSuccess={onDocumentLoadSuccess}
        loading={
          <div className="flex items-center justify-center py-12 text-sm text-foreground-muted">
            Loading PDF…
          </div>
        }
        error={
          <div className="flex items-center justify-center py-12 text-sm text-destructive">
            Failed to load PDF.
          </div>
        }
      >
        <div className="flex flex-col items-center gap-3">
          {Array.from({ length: numPages }, (_, i) => (
            <LazyPage
              key={i + 1}
              pageNumber={i + 1}
              onVisible={handlePageVisible}
            />
          ))}
        </div>
      </Document>
    </div>
  );
}
