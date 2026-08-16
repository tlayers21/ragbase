from pathlib import Path

from config.logging import setup_logging
from config.settings import SUPPORTED_OFFICE_EXTENSIONS

from . import anydoc_convert
from .base import BaseIngestor

logger = setup_logging(__name__)


class OfficeIngestor(BaseIngestor):
    """
    Ingestor for office and e-book formats (Word, PowerPoint, Excel, OpenDocument,
    RTF, EPUB, CSV) via anydoc, which converts them to GitHub-Flavored Markdown.

    anydoc is pure Rust with no ML models and no external services, so conversion
    is effectively instant and stays consistent with the project's local-only
    premise. There is no OCR or VLM stage here: these formats carry their text
    natively, and anything image-only inside them is out of scope.
    """

    def extract_text(self, source_path: str | Path, source_name: str) -> str:
        source_path = Path(source_path)
        suffix = source_path.suffix.lower()

        if suffix not in SUPPORTED_OFFICE_EXTENSIONS:
            raise ValueError(f"Expected an office document, got '{suffix}'")

        logger.info(f"Processing office document '{source_name}' ({suffix})...")

        result = anydoc_convert.to_markdown(source_path, source_name)
        if not result.ok:
            # No fallback exists for these formats - Docling doesn't cover them and
            # there is no VLM path, so surface the reason and let ingest() mark the
            # job as errored rather than storing an empty document.
            raise ValueError(f"anydoc could not convert '{source_name}': {result.detail}")

        return result.markdown
