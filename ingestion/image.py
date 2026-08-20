from functools import lru_cache
from pathlib import Path

from paddleocr import PaddleOCR

from config.logging import setup_logging
from config.models import get_model
from config.settings import SUPPORTED_IMAGE_EXTENSIONS
from utils.ollama_client import generate_stream

from .base import BaseIngestor
from .helpers import describe_image

logger = setup_logging(__name__)


@lru_cache(maxsize=1)
def _get_paddle_ocr() -> PaddleOCR:
    """Create and cache a PaddleOCR instance for image text extraction."""
    return PaddleOCR(
        lang="en",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


class ImageIngestor(BaseIngestor):
    """
    Ingestor for standalone image files.
    Combines PaddleOCR for printed text extraction with Qwen2.5-VL visual
    description.
    """

    SUPPORTED_EXTENSIONS = SUPPORTED_IMAGE_EXTENSIONS

    def extract_text(self, source_path: str | Path, source_name: str) -> str:
        source_path = Path(source_path)

        if source_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported image format '{source_path.suffix}'. "
                f"Supported: {self.SUPPORTED_EXTENSIONS}"
            )

        logger.info(f"Extracting text from image '{source_name}'...")

        ocr_text = self._run_ocr(source_path)
        description = self._run_vision(source_path, source_name)

        combined = self._combine(ocr_text, description, source_name)
        logger.info(f"Extraction complete for '{source_name}'")
        return combined

    def _run_ocr(self, image_path: Path) -> str:
        """
        Run PaddleOCR on the image to extract any printed text.
        Returns empty string if no text is found.
        """
        try:
            predictions = _get_paddle_ocr().predict(str(image_path))
            if not predictions:
                logger.debug("OCR found no text")
                return ""

            prediction = predictions[0]
            text_values = []

            # PaddleOCR renamed its result fields across versions - check both
            for field_name in ("rec_texts", "text_word"):
                if isinstance(prediction, dict):
                    field_value = prediction.get(field_name)
                else:
                    field_value = getattr(prediction, field_name, None)

                if field_value is None:
                    continue

                if isinstance(field_value, str):
                    text_values.append(field_value.strip())
                elif isinstance(field_value, (list, tuple)):
                    for item in field_value:
                        if isinstance(item, str):
                            cleaned_item = item.strip()
                            if cleaned_item:
                                text_values.append(cleaned_item)
                        elif item is not None:
                            cleaned_item = str(item).strip()
                            if cleaned_item:
                                text_values.append(cleaned_item)

            text = "\n".join(text_values).strip()
            if text:
                logger.debug(f"OCR extracted {len(text)} characters")
            else:
                logger.debug("OCR found no text")
            return text
        except Exception as e:
            logger.warning(f"OCR failed: {e}")
            return ""

    def _run_vision(self, image_path: Path, source_name: str) -> str:
        try:
            return describe_image(image_path, source_name)
        except Exception as e:
            logger.warning(f"Qwen2.5-VL failed for '{source_name}', using OCR only: {e}")
            return ""

    def _combine(self, ocr_text: str, description: str, source_name: str) -> str:
        """
        Fuse OCR text and Qwen2.5-VL description into a single coherent passage
        using the fast text model. If only one source is available, returns it
        directly without an LLM call.
        """
        if not ocr_text and not description:
            return ""
        if ocr_text and not description:
            return ocr_text
        if description and not ocr_text:
            return description

        # Both available - fuse with the fast text model
        prompt = f"""You have two descriptions of the same image.

    OCR extracted text:
    {ocr_text}

    Visual description:
    {description}

    You are given 2 parts of a description of the same image - the text on that
    image and a description of the visual components of the image itself. Combine
    them into a single coherent, well-written passage that captures all the
    information from both sources. Remove redundancy. Do not add information that
    isn't in either source. Output only the combined passage."""

        try:
            fused = "".join(generate_stream(prompt, model=get_model("summarize")))
            logger.debug(f"Fused OCR and Qwen2.5-VL output for '{source_name}'")
            return fused
        except Exception as e:
            logger.warning(f"Fusion failed for '{source_name}', falling back to concatenation: {e}")
            return f"Text found in image:\n{ocr_text}\n\nVisual description:\n{description}"
