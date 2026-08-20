from pathlib import Path

from config.logging import setup_logging
from config.settings import SUPPORTED_OFFICE_EXTENSIONS

from . import anydoc_convert
from .base import BaseIngestor

logger = setup_logging(__name__)


class OfficeIngestor(BaseIngestor):
    """Ingestor for office and e-book formats via anydoc, which emits GFM.

    No OCR or VLM stage: these formats carry their text natively.
    """

    def extract_text(self, source_path: str | Path, source_name: str) -> str:
        source_path = Path(source_path)
        suffix = source_path.suffix.lower()

        if suffix not in SUPPORTED_OFFICE_EXTENSIONS:
            raise ValueError(f"Expected an office document, got '{suffix}'")

        logger.info(f"Processing office document '{source_name}' ({suffix})...")

        result = anydoc_convert.to_markdown(source_path, source_name)
        if not result.ok:
            # No fallback for these formats, so error the job rather than store nothing
            raise ValueError(f"anydoc could not convert '{source_name}': {result.detail}")

        return result.markdown
