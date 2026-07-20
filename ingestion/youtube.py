import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from config.logging import setup_logging

from .base import BaseIngestor
from .helpers import transcribe

logger = setup_logging(__name__)


class YoutubeIngestor(BaseIngestor):
    """
    Ingestor for YouTube URLs and other video links.
    Downloads audio using yt-dlp then transcribes with Whisper.
    """

    # Only YouTube links are supported
    SUPPORTED_DOMAINS = {
        "youtube.com",
        "youtu.be",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
    }

    def extract_text(self, source_path: str | Path, source_name: str) -> str:
        """
        source_path here is actually the URL — we reuse the same interface
        as other ingestors but treat the path as a URL string.
        """
        url = str(source_path)

        if not self._is_valid_url(url):
            raise ValueError(f"Invalid URL: '{url}'. Must be a valid YouTube link.")

        logger.info(f"Downloading audio from '{source_name}' ({url})...")

        with tempfile.TemporaryDirectory() as tmp_dir:
            audio_path = self._download_audio(url, tmp_dir)
            logger.info(f"Download complete, transcribing '{source_name}'...")
            transcript = transcribe(audio_path)

        logger.info(f"Transcription complete for '{source_name}'")
        return transcript

    def _is_valid_url(self, url: str) -> bool:
        """Check if the URL is a supported YouTube link."""
        try:
            parsed = urlparse(url)
            return (
                parsed.scheme in {"http", "https"}
                and parsed.netloc.lower() in self.SUPPORTED_DOMAINS
            )
        except Exception:
            return False

    def _download_audio(self, url: str, output_dir: str) -> Path:
        """
        Download audio only from a video URL using yt-dlp.
        Returns the path to the downloaded audio file.
        """
        # yt-dlp is a heavy optional dependency — import lazily so it's only
        # loaded when a YouTube/video URL is actually being ingested.
        import yt_dlp

        output_template = os.path.join(output_dir, "audio.%(ext)s")

        ydl_opts = {
            "format": "bestaudio/best",  # Grab audio-only stream if available
            "outtmpl": output_template,  # Filename before conversion
            "quiet": True,  # Suppress console output
            "no_warnings": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",  # Use FFmpeg to extract/convert
                    "preferredcodec": "mp3",  # Convert to mp3
                }
            ],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        audio_path = Path(output_dir) / "audio.mp3"
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio download failed for URL: {url}")

        return audio_path
