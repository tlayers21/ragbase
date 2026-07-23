import concurrent.futures
from pathlib import Path

import whisper

from config.logging import setup_logging
from config.settings import VISION_TIMEOUT_SECONDS
from retrieval.graph import delete_source as delete_graph_source
from utils.cache import clear_cache
from utils.chromadb_client import get_collection, get_summary_collection
from utils.ollama_client import vision

logger = setup_logging(__name__)


def transcribe(audio_path: str | Path) -> str:
    """Transcribe audio/video file using Whisper. Returns timestamped transcript."""
    logger.info(f"Transcribing {audio_path}...")
    model = whisper.load_model("base")
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
            # Gap detected — flush current paragraph and start a new one
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


def delete_source(source: str, user_id: str) -> int:
    """
    Delete all chunks, summary, and graph data for a source.
    Returns the number of chunks deleted.
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

    return deleted_count
