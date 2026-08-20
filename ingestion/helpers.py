from pathlib import Path

import torch
import whisper

from config.logging import setup_logging
from config.paths import DATA_DIR, SOURCES_DIR
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


def describe_image(image_path: str | Path, source_name: str) -> str:
    """
    Describe an image using Qwen2.5-VL with the source name as context.
    """
    prompt = (
        f"This image is titled '{source_name}'. "
        f"Describe what you see in detail, using the title as context."
    )

    return vision(image_path, prompt, task="vision_handwrite")


def delete_source(source: str, user_id: str, remove_file: bool = True) -> int:
    """Delete all chunks, summary, and graph data for a source, returning chunks deleted.

    Pass remove_file=False from the re-ingest path, where the new upload already occupies
    the stored original's path.
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


def progress_checkpoint_path(source: str) -> Path:
    """Where the scanned-PDF page-resume checkpoint for a source lives.

    Derived in one place so the writer and the deleter cannot drift apart.
    """
    return DATA_DIR / f"{source}_progress.json"


def _delete_progress_checkpoint(source: str) -> None:
    """Discard the scanned-PDF page-resume checkpoint for a source, if one is on disk.

    Best-effort: leaving one behind makes a re-ingest resume at a page the new run never
    transcribed.
    """
    checkpoint = progress_checkpoint_path(source)
    try:
        checkpoint.unlink(missing_ok=True)
    except OSError as e:
        logger.warning(f"Could not delete progress checkpoint {checkpoint}: {e}")


def _delete_source_file(source: str, user_id: str) -> None:
    """Remove the stored original for a source, matching `{source}.*` since the name is a slug.

    Best-effort: a source with no stored original, such as YouTube, is the normal case.
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
