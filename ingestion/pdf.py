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
    SUPPORTED_PDF_EXTENSIONS,
    VISION_TIMEOUT_SECONDS,
)
from ingestion.queue import is_cancelled
from retrieval.pipeline import TextCleanup, TranscriptionRefinement

from .base import BaseIngestor, IngestionCancelled
from .helpers import describe_image, vision_with_timeout

logger = setup_logging(__name__)


class PdfIngestor(BaseIngestor):
    """
    Ingestor for PDF files. Handles three cases:
    - Normal PDFs: Docling extracts text,
      Qwen2.5-VL describes embedded images.
    - Handwritten PDFs: Detected via image placeholder ratio. Pages converted
      to images and transcribed one by one via Qwen2.5-VL with resume capability.
    - Mixed PDFs: Combination of text extraction and image description.
    """

    def extract_text(self, source_path: str | Path, source_name: str) -> str:
        source_path = Path(source_path)

        if source_path.suffix.lower() not in SUPPORTED_PDF_EXTENSIONS:
            raise ValueError(f"Expected a PDF file, got '{source_path.suffix}'")

        logger.info(f"Processing PDF '{source_name}'...")

        # Docling is a heavy optional dependency — import lazily so it's only
        # loaded when a PDF is actually being ingested.
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(source_path)
        doc = result.document

        if self._is_handwritten(doc):
            logger.info(
                f"Handwritten PDF detected for '{source_name}', switching to VLM mode (qwen2.5vl)"
            )
            return self._extract_handwritten(source_path, source_name)

        return self._extract_typed(doc, source_name)

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

            logger.info(f"Processing page {i + 1}/{len(pages)} of '{source_name}'...")

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

    # -- Typed PDF -------------------------------------------------------------
    def _extract_typed(self, doc, source_name: str) -> str:
        """
        Extract text from a typed PDF using Docling.
        Describes embedded images using qwen2.5vl.
        """
        text = self._extract_typed_pages(doc, source_name)
        text = self._describe_images(doc, text, source_name)

        # Clean up any placeholders that couldn't be converted
        remaining_images = text.count("<!-- image -->")
        remaining_formulas = text.count("<!-- formula-not-decoded -->")
        if remaining_images > 0:
            logger.warning(
                f"{remaining_images} image placeholders could not be replaced for '{source_name}'"
            )
            text = text.replace("<!-- image -->", "")
        if remaining_formulas > 0:
            logger.warning(
                f"{remaining_formulas} formula placeholders could not be converted "
                f"for '{source_name}'"
            )
            text = text.replace("<!-- formula-not-decoded -->", "[unrecognized formula]")

        return text

    def _extract_typed_pages(self, doc, source_name: str) -> str:
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

        cleaned_pages: list[str] = []
        sorted_pages = sorted(page_texts)

        for page_no in sorted_pages:
            if self.job_id and is_cancelled(self.job_id):
                raise IngestionCancelled(f"Ingestion of '{source_name}' was cancelled")

            raw_page_text = "\n".join(page_texts[page_no])
            if not raw_page_text.strip():
                cleaned_pages.append(raw_page_text)
                continue

            try:
                result = cleanup(raw_text=raw_page_text)
                cleaned_page_text = getattr(result, "cleaned_text", "")

                if not isinstance(cleaned_page_text, str) or not cleaned_page_text.strip():
                    raise ValueError("TextCleanup returned an empty or malformed response")

                cleaned_pages.append(cleaned_page_text)
            except Exception as e:
                logger.warning(
                    f"TextCleanup failed for page {page_no} of '{source_name}': {e}; using raw text"
                )
                cleaned_pages.append(raw_page_text)

        return "\n\n".join(cleaned_pages)

    def _describe_images(self, doc, text: str, source_name: str) -> str:
        """
        Find embedded images in the PDF and replace their <!-- image --> placeholders
        inline with Qwen2.5-VL descriptions, preserving document order.
        """
        image_count = 0

        with tempfile.TemporaryDirectory() as tmp_dir:
            for element, _ in doc.iterate_items():
                if self.job_id and is_cancelled(self.job_id):
                    raise IngestionCancelled(f"Ingestion of '{source_name}' was cancelled")

                try:
                    if hasattr(element, "image") and element.image is not None:
                        img_path = os.path.join(tmp_dir, f"img_{image_count}.png")
                        element.image.pil_image.save(img_path)

                        description = describe_image(img_path, source_name)

                        # Replace the next <!-- image --> placeholder in place
                        text = text.replace("<!-- image -->", f"\n[Image: {description}]\n", 1)
                        image_count += 1

                except Exception as e:
                    logger.warning(f"Failed to describe image {image_count}: {e}, skipping")
                    text = text.replace("<!-- image -->", "\n[Image could not be described]\n", 1)
                    continue

        if image_count > 0:
            logger.info(f"Described {image_count} embedded images from '{source_name}'")

        return text
