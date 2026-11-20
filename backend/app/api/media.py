"""Private source streaming and playback proxy endpoints."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Response, status

from app.models.schemas import PreviewResult
from app.services.preview import PreviewError, create_preview
from app.services.project_store import get_media, get_media_record, update_preview
from app.services.range_stream import byte_range, stream_file
from app.services.storage import StoragePathError, managed_path


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/media", tags=["media"])

MIME_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".webm": "video/webm",
}


def _record(media_id: str):
    record = get_media_record(media_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Media item not found.")
    return record


def _stored_file(record, path_key: str) -> Path:
    relative = record[path_key]
    if not relative:
        raise HTTPException(status_code=404, detail="A playback preview has not been generated.")
    try:
        path = managed_path(relative, must_exist=True)
    except FileNotFoundError as error:
        if path_key == "preview_relative_path":
            update_preview(record["id"], status="failed", relative_path=None, error="The generated preview file is missing.")
        raise HTTPException(status_code=410, detail="The stored video file is missing from the managed workspace.") from error
    except (StoragePathError, OSError, ValueError) as error:
        logger.error("Rejected unsafe managed media path for media id %s", record["id"])
        raise HTTPException(status_code=500, detail="The stored media path failed a workspace security check.") from error
    if not path.is_file():
        raise HTTPException(status_code=410, detail="The stored video file is missing from the managed workspace.")
    return path


def _content_type(record) -> str:
    return MIME_TYPES.get(Path(record["original_filename"]).suffix.lower(), "application/octet-stream")


def _head_file(path: Path, *, media_type: str, range_header: str | None) -> Response:
    size = path.stat().st_size
    start, end, partial = byte_range(range_header, size)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Cache-Control": "no-store",
        "Content-Disposition": "inline",
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return Response(status_code=206 if partial else 200, headers=headers, media_type=media_type)


@router.get("/{media_id}/stream")
def get_source_stream(media_id: str, range_header: str | None = Header(default=None, alias="Range")):
    record = _record(media_id)
    path = _stored_file(record, "source_relative_path")
    return stream_file(path, media_type=_content_type(record), range_header=range_header)


@router.head("/{media_id}/stream")
def head_source_stream(media_id: str, range_header: str | None = Header(default=None, alias="Range")):
    record = _record(media_id)
    path = _stored_file(record, "source_relative_path")
    return _head_file(path, media_type=_content_type(record), range_header=range_header)


@router.post("/{media_id}/preview", response_model=PreviewResult)
def post_preview(media_id: str) -> PreviewResult:
    _record(media_id)
    try:
        media = create_preview(media_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileNotFoundError as error:
        update_preview(media_id, status="failed", relative_path=None, error=str(error))
        raise HTTPException(status_code=410, detail=str(error)) from error
    except PreviewError as error:
        logger.warning("Playback preview failed for media id %s: %s", media_id, error)
        raise HTTPException(status_code=422, detail=str(error)) from error
    except StoragePathError as error:
        logger.error("Rejected unsafe source path for media id %s", media_id)
        raise HTTPException(status_code=500, detail="The source path failed a workspace security check.") from error
    return PreviewResult(media=media, message="Browser-compatible preview is ready. The imported source was not changed.")


@router.get("/{media_id}/preview/stream")
def get_preview_stream(media_id: str, range_header: str | None = Header(default=None, alias="Range")):
    record = _record(media_id)
    if record["preview_status"] != "ready":
        message = record["preview_error"] or "The playback preview is not ready."
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    path = _stored_file(record, "preview_relative_path")
    return stream_file(path, media_type="video/mp4", range_header=range_header)


@router.head("/{media_id}/preview/stream")
def head_preview_stream(media_id: str, range_header: str | None = Header(default=None, alias="Range")):
    record = _record(media_id)
    if record["preview_status"] != "ready":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The playback preview is not ready.")
    path = _stored_file(record, "preview_relative_path")
    return _head_file(path, media_type="video/mp4", range_header=range_header)
