import json
import os
import tempfile
from pathlib import Path

import dspy

from config.logging import setup_logging
from config.models import get_model
from config.paths import DATA_DIR
from config.settings import (
    HANDWRITTEN_IMAGE_THRESHOLD,
    HANDWRITTEN_TEXT_THRESHOLD,
    OLLAMA_URL,
    PDF_ANYDOC_MAX_BYTES,
    PDF_IMAGE_SCALE,
    PDF_SCANNED_CHARS_PER_PAGE,
    PDF_TEXT_PROBE_PAGES,
    SUPPORTED_PDF_EXTENSIONS,
    VISION_TIMEOUT_SECONDS,
)
from ingestion.queue import is_cancelled
from retrieval.pipeline import TextCleanup, TranscriptionRefinement

from . import anydoc_convert
from .base import BaseIngestor, IngestionCancelled
from .helpers import describe_image, vision_with_timeout

logger = setup_logging(__name__)


class PdfIngestor(BaseIngestor):
    """
    Ingestor for PDF files. Routes each file to one of three paths:

    - **Typed PDFs -> anydoc.** Pure-Rust Markdown conversion, seconds rather than
      minutes, and the output is already clean GFM so it needs no LLM cleanup pass.
    - **Scanned/handwritten PDFs -> Qwen2.5-VL.** Pages are rendered to images and
      transcribed one at a time, with page-level resume.
    - **Anything anydoc can't handle -> Docling.** The original pipeline, kept as a
      fallback for oversized files and unexpected conversion failures.

    `describe_images` is opt-in per file (the "Describe diagrams" checkbox in the
    UI). Embedded figures are largely vector drawings, which only Docling's layout
    model detects, so describing them means paying for a Docling pass on top of
    anydoc — worth it for slide decks full of diagrams, wasteful for prose.
    """

    def __init__(self, user_id: str, job_id: str | None = None, describe_images: bool = False):
        super().__init__(user_id, job_id=job_id)
        self.describe_images = describe_images

    def extract_text(self, source_path: str | Path, source_name: str) -> str:
        source_path = Path(source_path)

        if source_path.suffix.lower() not in SUPPORTED_PDF_EXTENSIONS:
            raise ValueError(f"Expected a PDF file, got '{source_path.suffix}'")

        logger.info(f"Processing PDF '{source_name}'...")

        if self._looks_scanned(source_path, source_name):
            logger.info(
                f"Scanned/handwritten PDF detected for '{source_name}', "
                f"switching to VLM mode (qwen2.5vl)"
            )
            return self._extract_handwritten(source_path, source_name)

        size = source_path.stat().st_size
        if size >= PDF_ANYDOC_MAX_BYTES:
            logger.info(
                f"'{source_name}' is {size / 1e6:.0f}MB, above the anydoc memory ceiling — "
                f"using Docling instead"
            )
            return self._extract_with_docling(source_path, source_name)

        self._set_estimate(30)  # anydoc finishes in seconds; the summary call dominates
        result = anydoc_convert.to_markdown(source_path, source_name)

        if result.ok:
            return self._append_image_descriptions(result.markdown, source_path, source_name)

        if result.needs_ocr:
            # The text probe above can be fooled by a PDF whose text layer is a few
            # stray page numbers. anydoc inspects every page, so trust it over the probe.
            logger.info(f"anydoc reports '{source_name}' needs OCR, switching to VLM mode")
            return self._extract_handwritten(source_path, source_name)

        logger.warning(
            f"anydoc failed on '{source_name}' ({result.status}: {result.detail}), "
            f"falling back to Docling"
        )
        return self._extract_with_docling(source_path, source_name)

    # -- Routing helpers -------------------------------------------------------
    def _looks_scanned(self, pdf_path: Path, source_name: str) -> bool:
        """
        Decide whether a PDF has a usable text layer, by sampling pages with PyMuPDF.

        This runs before anydoc on purpose. anydoc buffers the entire file to answer
        the same question, and on large scanned books that means gigabytes of RAM for
        an answer PyMuPDF gives in well under a second from page metadata.

        Returning False only means "there is text" — anydoc still gets the final say
        via its own `OCR is required` verdict.
        """
        try:
            import pymupdf
        except ImportError as e:
            logger.warning(f"PyMuPDF unavailable for the text probe on '{source_name}': {e}")
            return False

        try:
            doc = pymupdf.open(pdf_path)
        except Exception as e:
            logger.warning(f"Could not open '{source_name}' for the text probe: {e}")
            return False

        try:
            pages = doc.page_count
            if pages == 0:
                return False

            step = max(1, pages // PDF_TEXT_PROBE_PAGES)
            sampled = 0
            chars = 0
            for page_no in range(0, pages, step):
                chars += len(doc[page_no].get_text().strip())
                sampled += 1
        except Exception as e:
            logger.warning(f"Text probe failed for '{source_name}': {e}; assuming typed")
            return False
        finally:
            doc.close()

        per_page = chars / sampled
        logger.info(
            f"Text probe for '{source_name}': {per_page:.0f} chars/page "
            f"over {sampled} of {pages} pages"
        )
        return per_page < PDF_SCANNED_CHARS_PER_PAGE

    def _append_image_descriptions(self, markdown: str, pdf_path: Path, source_name: str) -> str:
        """
        Optionally describe the PDF's figures and append them to anydoc's Markdown.

        anydoc returns one blob with no page provenance, so descriptions can't be
        interleaved the way the Docling path does it — they are appended as a trailing
        section tagged with the page each figure came from. Chunking is by word count,
        so the descriptions still become retrievable chunks; they just aren't adjacent
        to their page's prose.
        """
        if not self.describe_images:
            return markdown

        logger.info(f"Describing figures in '{source_name}' (opt-in, requires a Docling pass)")
        doc = self._convert_with_docling(pdf_path, source_name, for_images_only=True)
        if doc is None:
            return markdown

        images_by_page = self._describe_images(doc, source_name)
        if not images_by_page:
            return markdown

        blocks = [
            f"[Image (page {page_no}): {description}]"
            for page_no in sorted(images_by_page)
            for description in images_by_page[page_no]
        ]
        return f"{markdown}\n\n--- Figures ---\n\n" + "\n\n".join(blocks)

    # -- Handwritten PDF -------------------------------------------------------
    def _is_handwritten(self, doc) -> bool:
        """
        Detect if a PDF is handwritten by checking if Docling only returned
        image placeholders with very little real text content.
        """
        text = doc.export_to_markdown()
        image_count = text.count("<!-- image -->")
        cleaned = text.replace("<!-- image -->", "").strip()

        if image_count > HANDWRITTEN_IMAGE_THRESHOLD and len(cleaned) < HANDWRITTEN_TEXT_THRESHOLD:
            return True

        if image_count > 0 and len(cleaned) < (image_count * 50):  # <50 chars of text per image
            return True

        return False

    def _extract_handwritten(self, pdf_path: Path, source_name: str) -> str:
        """
        Extract text from a handwritten PDF by converting each page to an image
        and running Qwen2.5-VL on it. Saves progress after each page so the job
        can resume if interrupted.

        Each page gets up to MAX_RETRIES attempts. On each retry the timeout
        is increased to give Qwen2.5-VL more time for difficult pages.
        """
        # pdf2image is a heavy optional dependency — import lazily so it's
        # only loaded when a handwritten PDF is actually being transcribed.
        from pdf2image import convert_from_path

        MAX_RETRIES = 3
        BASE_TIMEOUT = VISION_TIMEOUT_SECONDS

        progress_file = DATA_DIR / f"{source_name}_progress.json"

        # Resume from previous progress if available
        if progress_file.exists():
            with open(progress_file, "r") as f:
                progress = json.load(f)
            full_text = progress["text"]
            start_page = progress["last_page"] + 1
            logger.info(f"Resuming '{source_name}' from page {start_page + 1}")
        else:
            full_text = ""
            start_page = 0

        pages = convert_from_path(pdf_path)
        pages_total = len(pages)
        logger.info(f"Found {pages_total} pages, starting from page {start_page + 1}")
        self._set_estimate(pages_total * 45)  # ~45s/page observed for Qwen2.5-VL transcription

        # Write the progress file before the first page so a crash mid-page-1
        # still leaves a resumable state on disk
        with open(progress_file, "w") as f:
            json.dump(
                {"text": full_text, "last_page": start_page - 1, "pages_total": pages_total}, f
            )

        refine_transcription = dspy.Predict(TranscriptionRefinement)
        refine_lm = dspy.LM(model=f"ollama/{get_model('text_cleanup')}", api_base=OLLAMA_URL)
        refine_transcription.set_lm(refine_lm)

        for i, page in enumerate(pages[start_page:], start=start_page):
            if self.job_id and is_cancelled(self.job_id):
                raise IngestionCancelled(f"Ingestion of '{source_name}' was cancelled")

            logger.info(f"Processing page {i + 1}/{pages_total} of '{source_name}'...")
            # i is absolute even on a resumed job, so a resume correctly picks the
            # bar up where it left off rather than restarting at page 1.
            self._set_progress(i + 1, pages_total, "page")

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                page.save(tmp.name, "PNG")
                tmp_path = tmp.name

            page_text = None

            try:
                for attempt in range(1, MAX_RETRIES + 1):
                    # Each retry gets more time
                    timeout = BASE_TIMEOUT * attempt
                    logger.info(
                        f"Page {i + 1} — attempt {attempt}/{MAX_RETRIES} (timeout: {timeout}s)"
                    )
                    try:
                        page_text = self._transcribe_page(tmp_path, i + 1, timeout=timeout)
                        break  # Success — stop retrying
                    except TimeoutError:
                        if attempt < MAX_RETRIES:
                            logger.warning(
                                f"Page {i + 1} timed out on attempt {attempt}, "
                                f"retrying with {timeout * 2}s timeout..."
                            )
                        else:
                            logger.error(
                                f"Page {i + 1} failed all {MAX_RETRIES} attempts. "
                                f"Leaving blank — you can re-ingest this source to retry."
                            )
                    except Exception as e:
                        logger.error(f"Page {i + 1} attempt {attempt} failed: {e}")
                        if attempt == MAX_RETRIES:
                            logger.error(
                                f"Page {i + 1} failed all {MAX_RETRIES} attempts. "
                                f"Leaving blank — you can re-ingest to retry."
                            )
                        break

                if page_text:
                    try:
                        result = refine_transcription(raw_transcription=page_text)
                        refined_page_text = getattr(result, "refined_transcription", "")

                        if not isinstance(refined_page_text, str) or not refined_page_text.strip():
                            raise ValueError(
                                "TranscriptionRefinement returned an empty or malformed response"
                            )

                        page_text = refined_page_text
                    except Exception as e:
                        logger.warning(
                            f"TranscriptionRefinement failed for page {i + 1} of "
                            f"'{source_name}': {e}; using raw transcription"
                        )

                if page_text:
                    full_text += f"\n\n--- Page {i + 1} ---\n{page_text}"
                else:
                    full_text += f"\n\n--- Page {i + 1} ---\n[Page could not be transcribed]"

            finally:
                os.remove(tmp_path)

            # Save progress after every page regardless of outcome
            with open(progress_file, "w") as f:
                json.dump({"text": full_text, "last_page": i, "pages_total": pages_total}, f)

        # Clean up progress file when done
        if progress_file.exists():
            progress_file.unlink()

        return full_text

    def _transcribe_page(self, image_path: str, page_num: int, timeout: int | None = None) -> str:
        timeout = timeout or VISION_TIMEOUT_SECONDS
        prompt = (
            "Transcribe the handwritten content on this page verbatim, line by line, "
            "exactly as it appears. Do not paraphrase, summarize, explain, or reason "
            "about the math — write down only what is literally written on the page, "
            "in the same order it appears. Write mathematical expressions in LaTeX "
            "notation, matching the page as closely as possible. Do not add any notes, "
            "commentary, or statements about the transcription itself. If a word or "
            "symbol is genuinely illegible, write [illegible] in its place — do not "
            "guess or substitute a plausible-looking alternative."
        )
        return vision_with_timeout(image_path, prompt, task="vision_handwrite", timeout=timeout)

    # -- Docling fallback ------------------------------------------------------
    def _convert_with_docling(
        self, pdf_path: Path, source_name: str, for_images_only: bool = False
    ):
        """
        Run Docling's converter and return the parsed document, or None on failure.

        `for_images_only` is the cheap configuration used when anydoc already supplied
        the text and Docling is needed solely to locate figures: OCR and table
        structure analysis are both switched off, leaving only layout detection.
        """
        # Docling is a heavy optional dependency — import lazily so it's only
        # loaded when a PDF actually needs it.
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipeline_options = PdfPipelineOptions(
            # Without this, PictureItem.get_image() returns None for every image and
            # _describe_images() silently finds nothing to describe.
            generate_picture_images=True,
            images_scale=PDF_IMAGE_SCALE,
            # Docling defaults ocr_options.kind to "auto", which resolves to whichever
            # OCR engine happens to be installed. Pinning RapidOCR keeps extraction
            # reproducible instead of changing silently when dependencies shift.
            ocr_options=RapidOcrOptions(),
        )
        if for_images_only:
            pipeline_options.do_ocr = False
            pipeline_options.do_table_structure = False

        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )

        try:
            return converter.convert(pdf_path).document
        except Exception as e:
            logger.error(f"Docling conversion failed for '{source_name}': {e}")
            return None

    def _extract_with_docling(self, pdf_path: Path, source_name: str) -> str:
        """
        The original Docling pipeline, kept for PDFs anydoc declines: files above the
        memory ceiling, and conversions that crash or time out.
        """
        doc = self._convert_with_docling(pdf_path, source_name)
        if doc is None:
            raise ValueError(f"Neither anydoc nor Docling could extract text from '{source_name}'")

        if self._is_handwritten(doc):
            logger.info(
                f"Handwritten PDF detected for '{source_name}', switching to VLM mode (qwen2.5vl)"
            )
            return self._extract_handwritten(pdf_path, source_name)

        return self._extract_typed(doc, source_name)

    # -- Typed PDF -------------------------------------------------------------
    def _extract_typed(self, doc, source_name: str) -> str:
        """
        Extract text from a typed PDF using Docling.
        Describes embedded images using qwen2.5vl and interleaves them by page.
        """
        # Gated on the same per-file opt-in as the anydoc path, so the checkbox means
        # the same thing no matter which extractor handled the file.
        images_by_page = self._describe_images(doc, source_name) if self.describe_images else {}
        text = self._extract_typed_pages(doc, source_name, images_by_page)

        remaining_formulas = text.count("<!-- formula-not-decoded -->")
        if remaining_formulas > 0:
            logger.warning(
                f"{remaining_formulas} formula placeholders could not be converted "
                f"for '{source_name}'"
            )
            text = text.replace("<!-- formula-not-decoded -->", "[unrecognized formula]")

        return text

    def _extract_typed_pages(
        self, doc, source_name: str, images_by_page: dict[int, list[str]] | None = None
    ) -> str:
        """
        Export and clean typed PDF text one page at a time.

        This keeps the cleanup failure domain small: if one page's LLM-based
        cleanup fails, that page falls back to its original raw text unchanged.
        """
        cleanup = dspy.Predict(TextCleanup)
        cleanup_lm = dspy.LM(model=f"ollama/{get_model('text_cleanup')}", api_base=OLLAMA_URL)
        cleanup.set_lm(cleanup_lm)
        page_texts: dict[int, list[str]] = {}

        for item in getattr(doc, "texts", []):
            text = getattr(item, "text", "")
            prov = getattr(item, "prov", [])

            if not text or not prov:
                continue

            page_no = getattr(prov[0], "page_no", None)
            if page_no is None:
                continue

            page_texts.setdefault(page_no, []).append(text)

        images_by_page = images_by_page or {}
        cleaned_pages: list[str] = []
        # Union of both maps: a page can hold only a diagram and no extractable text,
        # and its description would be dropped if we walked text pages alone.
        sorted_pages = sorted(set(page_texts) | set(images_by_page))

        for position, page_no in enumerate(sorted_pages, start=1):
            if self.job_id and is_cancelled(self.job_id):
                raise IngestionCancelled(f"Ingestion of '{source_name}' was cancelled")

            # Counts pages that produced content, not the PDF's true page count —
            # sorted_pages is the union of the text and image maps, so a wholly empty
            # page never appears. The total is therefore a lower bound, which is the
            # right way round: the bar can't stall short of 100%.
            self._set_progress(position, len(sorted_pages), "page")

            raw_page_text = "\n".join(page_texts.get(page_no, []))
            page_output = raw_page_text

            if raw_page_text.strip():
                try:
                    result = cleanup(raw_text=raw_page_text)
                    cleaned_page_text = getattr(result, "cleaned_text", "")

                    if not isinstance(cleaned_page_text, str) or not cleaned_page_text.strip():
                        raise ValueError("TextCleanup returned an empty or malformed response")

                    page_output = cleaned_page_text
                except Exception as e:
                    logger.warning(
                        f"TextCleanup failed for page {page_no} of '{source_name}': {e}; "
                        f"using raw text"
                    )

            # Descriptions go after the page's prose so a chunk covering this page
            # carries both, and cleanup never sees VLM output as "raw text to fix".
            descriptions = images_by_page.get(page_no, [])
            if descriptions:
                blocks = "\n".join(f"[Image: {d}]" for d in descriptions)
                page_output = f"{page_output}\n{blocks}" if page_output.strip() else blocks

            cleaned_pages.append(page_output)

        return "\n\n".join(cleaned_pages)

    def _describe_images(self, doc, source_name: str) -> dict[int, list[str]]:
        """
        Describe each embedded image with Qwen2.5-VL, keyed by the page it appears on.

        Returns {page_no: [description, ...]} so the caller can interleave descriptions
        with that page's text. Keying by page (rather than substituting Docling's
        `<!-- image -->` markdown placeholder) is deliberate: page text is assembled
        from `doc.texts`, which never contains those placeholders, so placeholder
        substitution silently matched nothing and every image was dropped.
        """
        images_by_page: dict[int, list[str]] = {}
        described = 0

        with tempfile.TemporaryDirectory() as tmp_dir:
            for index, picture in enumerate(getattr(doc, "pictures", [])):
                if self.job_id and is_cancelled(self.job_id):
                    raise IngestionCancelled(f"Ingestion of '{source_name}' was cancelled")

                if not picture.prov:
                    continue
                page_no = picture.prov[0].page_no

                try:
                    # Requires generate_picture_images=True on the pipeline options —
                    # otherwise this is None for every picture.
                    image = picture.get_image(doc)
                    if image is None:
                        continue

                    img_path = os.path.join(tmp_dir, f"img_{index}.png")
                    image.save(img_path)

                    description = describe_image(img_path, source_name)
                    if description and description.strip():
                        images_by_page.setdefault(page_no, []).append(description.strip())
                        described += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to describe image {index} on page {page_no} of "
                        f"'{source_name}': {e}, skipping"
                    )
                    continue

        if described:
            logger.info(f"Described {described} embedded images from '{source_name}'")

        return images_by_page
