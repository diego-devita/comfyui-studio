"""ComfyUI Studio — Centralized media file serving.

Single source of truth for serving images and videos from disk.
All endpoints that need to return media files should use serve_media().
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from config import STUDIO_DIR

router = APIRouter()

# Allowed media extensions
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}
_VIDEO_EXT = {".mp4", ".webm", ".mov", ".avi"}
_MEDIA_EXT = _IMAGE_EXT | _VIDEO_EXT

_MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
}

# 24h cache — these files don't change once written
_CACHE_HEADER = "public, max-age=86400, immutable"

# Cache resolved studio path (doesn't change at runtime)
_STUDIO_PREFIX = str(STUDIO_DIR.resolve()) + "/"


def serve_media(abs_path: Path) -> FileResponse:
    """Serve a media file from an absolute path.

    Validates the file exists, has a media extension, and lives under STUDIO_DIR.
    Returns a FileResponse with Cache-Control and correct media type.
    Starlette FileResponse handles Range requests automatically.
    """
    # Resolve to catch symlink tricks
    resolved = abs_path.resolve()

    # Must be under STUDIO_DIR
    if not str(resolved).startswith(_STUDIO_PREFIX):
        raise HTTPException(403, "Access denied")

    if not resolved.is_file():
        raise HTTPException(404, "File not found")

    ext = resolved.suffix.lower()
    if ext not in _MEDIA_EXT:
        raise HTTPException(403, "Not a media file")

    media_type = _MIME_MAP.get(ext, "application/octet-stream")

    return FileResponse(
        path=resolved,
        media_type=media_type,
        headers={"Cache-Control": _CACHE_HEADER},
    )


@router.get("/api/files/{file_path:path}")
async def serve_file(file_path: str):
    """Serve any media file by relative path from STUDIO_DIR.

    Examples:
      /api/files/assets/output/job-123/video/out.mp4
      /api/files/assets/input/image.png
      /api/files/assets/images/media/abc.jpg
    """
    # Block path traversal
    if ".." in file_path:
        raise HTTPException(403, "Invalid path")

    abs_path = STUDIO_DIR / file_path
    return serve_media(abs_path)
