import os
import tempfile
from pathlib import Path

from config.logging import setup_logging

from .base import BaseIngestor

logger = setup_logging(__name__)


class TextIngestor(BaseIngestor):
    """Ingestor for plain text and markdown files, and raw text strings."""

    def extract_text(self, source_path: str | Path, source_name: str) -> str:
        """Read text directly from a .txt or .md file."""
        source_path = Path(source_path)
        logger.info(f"Reading text from '{source_name}'")
        with open(source_path, "r", encoding="utf-8") as f:
            return f.read()

    def ingest_string(self, text: str, source_name: str) -> int:
        # Create a temp file since ingest function expects a file path
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(text)
            tmp_path = f.name
        try:
            return self.ingest(tmp_path, source_name)
        finally:
            os.remove(tmp_path)
