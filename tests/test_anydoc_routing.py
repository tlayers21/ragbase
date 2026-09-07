"""Routing for PDFs anydoc will not convert.

anydoc signals a missing text layer by raising, and RAGbase reads that signal to pick
between the VLM and Docling. The signal has changed shape once already (0.2.4 replaced an
`UnsupportedError` carrying "OCR is required" with a distinct `NeedsOcrError`), and when it
changes the failure is silent: scanned PDFs keep ingesting, down the wrong path. These
tests pin the signal and the split.
"""

import pytest

from ingestion.anydoc_convert import AnydocResult, to_markdown


@pytest.fixture
def scanned_pdf(tmp_path):
    """A one-page PDF holding a blank image and no text layer."""
    pymupdf = pytest.importorskip("pymupdf")

    path = tmp_path / "scanned.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200))
    pix.set_rect(pix.irect, (255, 255, 255))
    page.insert_image(pymupdf.Rect(0, 0, 200, 200), pixmap=pix)
    doc.save(path)
    doc.close()
    return path


def test_textless_pdf_reports_ocr_required(scanned_pdf):
    """The real anydoc exception must still map to ocr_required, not a generic error.

    This is the coupling that broke on the 0.2.4 upgrade. Exercises the child process
    against the installed wheel on purpose - a mocked exception would not have caught it.
    """
    result = to_markdown(scanned_pdf, "scanned.pdf")

    assert result.needs_ocr, f"expected ocr_required, got {result.status}: {result.detail}"
    assert result.page_count == 1
    assert result.ocr_pages == 1


def test_fully_scanned_document_goes_to_the_vlm():
    assert AnydocResult(status="ocr_required", ocr_pages=580, page_count=580).mostly_needs_ocr


def test_one_scanned_page_in_a_book_does_not_go_to_the_vlm():
    """696 typed pages must not be transcribed page by page because one page is a scan."""
    assert not AnydocResult(status="ocr_required", ocr_pages=1, page_count=696).mostly_needs_ocr


def test_missing_page_counts_fall_back_to_the_vlm():
    """An older worker, or an unparsed verdict, reports no counts - keep the old behavior."""
    assert AnydocResult(status="ocr_required").mostly_needs_ocr
