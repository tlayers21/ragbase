import asyncio
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from api.guards import require_finished
from config.logging import setup_logging
from config.paths import SOURCES_DIR
from config.runtime import USER_ID

logger = setup_logging(__name__)
router = APIRouter(prefix="/sources", tags=["sources"])

_KNOWN_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
}


def _locate_source_file(source: str) -> tuple[Path, int] | None:
    """Find the stored file for a source and its size, or None if there isn't one.

    Runs off the event loop: exists()/glob()/stat() are three separate synchronous
    filesystem round-trips, and SOURCES_DIR holds every original the user has ever
    ingested, so the glob is not free once that directory is large.
    """
    source_dir = SOURCES_DIR / USER_ID
    if not source_dir.exists():
        return None
    matches = sorted(source_dir.glob(f"{source}.*"))
    if not matches:
        return None
    return matches[0], matches[0].stat().st_size


@router.api_route("/{source}/file", methods=["GET", "HEAD"])
async def get_source_file(source: str, request: Request):
    """Serve the stored original for a source, HEAD included for content-type sniffing.

    A fallback for clients that cannot reach the Next.js static route.
    """
    # 409 while in flight - the original is servable from upload, long before "done"
    await require_finished(source)

    located = await asyncio.to_thread(_locate_source_file, source)
    if located is None:
        raise HTTPException(status_code=404, detail=f"No file stored for source '{source}'")

    path, size = located
    suffix = path.suffix.lower()
    media_type = (
        _KNOWN_MIME.get(suffix) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    )

    # Fetched both as <img src> and via fetch(), so the two cache entries must stay apart
    headers = {"Vary": "Origin"}

    if request.method == "HEAD":
        return Response(
            headers={
                **headers,
                "Content-Type": media_type,
                "Content-Length": str(size),
            }
        )

    return FileResponse(path=str(path), media_type=media_type, filename=path.name, headers=headers)
