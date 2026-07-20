"use client";

import { useState, useCallback, useRef, memo, useMemo } from "react";
import { Document, Page, pdfjs } from "react-pdf";

pdfjs.GlobalWorkerOptions.workerSrc = `https://cdn.jsdelivr.net/npm/pdfjs-dist@5.4.296/build/pdf.worker.min.mjs`;

const PAGE_WIDTH = 520;
const EST_PAGE_HEIGHT = Math.round(PAGE_WIDTH * 1.414);

const LazyPage = memo(function LazyPage({
  pageNumber,
  onVisible,
}: {
  pageNumber: number;
  onVisible: (page: number, visible: boolean) => void;
}) {
  const [shouldRender, setShouldRender] = useState(false);

  const ref = useCallback(
    (el: HTMLDivElement | null) => {
      if (!el) return;
      const obs = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) setShouldRender(true);
          onVisible(pageNumber, entry.isIntersecting);
        },
        { root: null, threshold: 0.01 }
      );
      obs.observe(el);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  return (
    <div ref={ref} style={{ minHeight: EST_PAGE_HEIGHT }}>
      {shouldRender ? (
        <Page
          pageNumber={pageNumber}
          width={PAGE_WIDTH}
          renderTextLayer={false}
          renderAnnotationLayer={false}
        />
      ) : (
        <div
          style={{ width: PAGE_WIDTH, height: EST_PAGE_HEIGHT }}
          className="rounded bg-surface animate-pulse"
        />
      )}
    </div>
  );
});

interface PDFPreviewProps {
  url: string;
}

export default function PDFPreview({ url }: PDFPreviewProps) {
  const [numPages, setNumPages] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const visiblePagesRef = useRef<Set<number>>(new Set());

  const pdfOptions = useMemo(
    () => ({
      cMapUrl: `https://cdn.jsdelivr.net/npm/pdfjs-dist@5.4.296/cmaps/`,
      cMapPacked: true,
    }),
    []
  );

  const onDocumentLoadSuccess = useCallback(
    ({ numPages: n }: { numPages: number }) => {
      setNumPages(n);
      visiblePagesRef.current.clear();
    },
    []
  );

  const handlePageVisible = useCallback((page: number, visible: boolean) => {
    if (visible) {
      visiblePagesRef.current.add(page);
    } else {
      visiblePagesRef.current.delete(page);
    }
    const min = Math.min(...Array.from(visiblePagesRef.current));
    if (isFinite(min)) {
      setCurrentPage((prev) => (prev === min ? prev : min));
    }
  }, []);

  return (
    <div style={{ height: "65vh", overflowY: "auto" }}>
      <div className="flex flex-col gap-2 py-2">
        {numPages > 1 && (
          <div className="flex justify-center sticky top-2 z-10">
            <span className="text-[10px] tabular-nums text-foreground-muted bg-background/80 backdrop-blur-sm px-2 py-0.5 rounded-full border border-border/50">
              Page {currentPage} of {numPages}
            </span>
          </div>
        )}
        <Document
          file={url}
          onLoadSuccess={onDocumentLoadSuccess}
          options={pdfOptions}
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
          <div className="flex flex-col items-center gap-3 pb-4">
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
    </div>
  );
}