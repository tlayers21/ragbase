import concurrent.futures
from pathlib import Path

import torch
import whisper

from config.logging import setup_logging
from config.paths import DATA_DIR, SOURCES_DIR
from config.settings import VISION_TIMEOUT_SECONDS
from retrieval.graph import delete_source as delete_graph_source
from utils.cache import clear_cache
from utils.chromadb_client import get_collection, get_summary_collection
from utils.ollama_client import vision

logger = setup_logging(__name__)


def transcribe(audio_path: str | Path) -> str:
    """Transcribe audio/video file using Whisper. Returns timestamped transcript."""
    logger.info(f"Transcribing {audio_path}...")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = whisper.load_model("base", device=device)
    result = model.transcribe(str(audio_path), fp16=False)
    return format_transcript(result["segments"])


def format_transcript(segments: list[dict], paragraph_gap_seconds: float = 3.0) -> str:
    """
    Format Whisper segments into readable paragraphs with timestamps.
    Groups consecutive segments together until there is a gap of more than
    paragraph_gap_seconds between them, then starts a new paragraph.
    """
    if not segments:
        return ""

    paragraphs = []
    current_lines = []
    current_start = _seconds_to_timestamp(segments[0]["start"])
    prev_end = segments[0]["end"]

    for segment in segments:
        gap = segment["start"] - prev_end

        if gap > paragraph_gap_seconds and current_lines:
            # Gap detected - flush current paragraph and start a new one
            paragraph_text = " ".join(current_lines)
            paragraphs.append(f"[{current_start}] {paragraph_text}")
            current_lines = []
            current_start = _seconds_to_timestamp(segment["start"])

        current_lines.append(segment["text"].strip())
        prev_end = segment["end"]

    # Flush final paragraph
    if current_lines:
        paragraph_text = " ".join(current_lines)
        paragraphs.append(f"[{current_start}] {paragraph_text}")

    return "\n\n".join(paragraphs)


def _seconds_to_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def vision_with_timeout(image_path: str, prompt: str, task: str, timeout: int) -> str:
    """
    Run a vision model call with a thread-based timeout.

    This is thread-safe because it works from any calling thread, and it is
    cross-platform because it does not depend on POSIX-only signal support.
    Raises TimeoutError if the call exceeds the timeout.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(vision, image_path, prompt, task=task)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            raise TimeoutError(f"Vision model timed out after {timeout}s") from exc


def describe_image(image_path: str | Path, source_name: str) -> str:
    """
    Describe an image using Qwen2.5-VL with the source name as context.
    """
    prompt = (
        f"This image is titled '{source_name}'. "
        f"Describe what you see in detail, using the title as context."
    )

    return vision_with_timeout(
        image_path, prompt, task="vision_handwrite", timeout=VISION_TIMEOUT_SECONDS
    )


def delete_source(source: str, user_id: str, remove_file: bool = True) -> int:
    """
    Delete all chunks, summary, and graph data for a source.
    Returns the number of chunks deleted.

    `remove_file` also discards the stored original in `data/sources/`. Pass False
    from the re-ingestion cleanup path in `BaseIngestor.ingest`: the API writes the
    new upload to that exact path *before* enqueueing the job, so wiping the old
    source's file there would delete the file the running ingestion just stored.
    """
    collection = get_collection(user_id)
    summary_collection = get_summary_collection(user_id)

    results = collection.get(where={"source": source})
    deleted_count = 0
    if results["ids"]:
        collection.delete(ids=results["ids"])
        deleted_count = len(results["ids"])
        logger.info(f"Deleted {deleted_count} chunks from '{source}'")

    summary_results = summary_collection.get(where={"source": source})
    if summary_results["ids"]:
        summary_collection.delete(ids=summary_results["ids"])
        logger.info(f"Deleted summary for '{source}'")

    delete_graph_source(source, user_id)
    clear_cache(user_id)
    _delete_progress_checkpoint(source)
    if remove_file:
        _delete_source_file(source, user_id)

    return deleted_count


def _delete_progress_checkpoint(source: str) -> None:
    """
    Discard the scanned-PDF page-resume checkpoint for a source, if one is on disk.

    `PdfIngestor` writes `data/{source}_progress.json` after every page so a long VLM
    transcription can resume, and unlinks it only on success. A cancelled or failed run
    therefore left it behind, and re-ingesting the same file resumed from the old page
    offset - skipping pages that were never transcribed into the new run. Deleting the
    source has to clear it too, since that is the point where its text stops existing.

    Best-effort: most sources never create one.
    """
    checkpoint = DATA_DIR / f"{source}_progress.json"
    try:
        checkpoint.unlink(missing_ok=True)
    except OSError as e:
        logger.warning(f"Could not delete progress checkpoint {checkpoint}: {e}")


def _delete_source_file(source: str, user_id: str) -> None:
    """
    Remove the stored original for a source, if one was kept.

    Deleting only the chunks left the uploaded file behind forever: the source
    vanished from every list in the UI while its PDF/image stayed on disk, so
    `data/sources/` grew without bound and nothing in the app could reach the file
    to clean it up. Matches `{source}.*` because the source name is a slug that
    carries no extension of its own.

    Best-effort by design - a source with no stored original (YouTube, whose
    transcript is never written to disk) is the normal case, and a failure here
    must not turn a successful delete into an error.
    """
    source_dir = SOURCES_DIR / user_id
    if not source_dir.exists():
        return
    for path in source_dir.glob(f"{source}.*"):
        try:
            path.unlink()
            logger.info(f"Deleted stored file for '{source}': {path.name}")
        except OSError as e:
            logger.warning(f"Could not delete stored file {path}: {e}")
