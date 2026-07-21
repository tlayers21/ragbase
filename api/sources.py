import mimetypes

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

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


@router.api_route("/{source}/file", methods=["GET", "HEAD"])
async def get_source_file(source: str, request: Request):
    """Serve the stored original file for a source. HEAD is supported for content-type sniffing."""
    source_dir = SOURCES_DIR / USER_ID
    if not source_dir.exists():
        raise HTTPException(status_code=404, detail="No stored source files")

    # Find the file matching this source name (any extension)
    matches = list(source_dir.glob(f"{source}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail=f"No file stored for source '{source}'")

    path = matches[0]
    suffix = path.suffix.lower()
    media_type = (
        _KNOWN_MIME.get(suffix) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    )

    if request.method == "HEAD":
        return Response(
            headers={"Content-Type": media_type, "Content-Length": str(path.stat().st_size)}
        )

    return FileResponse(path=str(path), media_type=media_type, filename=path.name)
