from pathlib import Path

from config.logging import setup_logging
from config.settings import SUPPORTED_VIDEO_EXTENSIONS

from .base import BaseIngestor
from .helpers import transcribe

logger = setup_logging(__name__)


class VideoIngestor(BaseIngestor):
    """Ingestor for local video files. Transcribes audio using Whisper."""

    SUPPORTED_EXTENSIONS = SUPPORTED_VIDEO_EXTENSIONS

    def extract_text(self, source_path: str | Path, source_name: str) -> str:
        source_path = Path(source_path)

        if source_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported video format '{source_path.suffix}'. "
                f"Supported: {self.SUPPORTED_EXTENSIONS}"
            )

        logger.info(f"Transcribing video '{source_name}'...")
        transcript = transcribe(source_path)
        logger.info(f"Transcription complete for '{source_name}'")
        return transcript
