"""Managed upload storage with path containment checks."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import settings
from app.models.schemas import MediaOut
from app.services.media_validation import MediaToolError, MediaValidationError, ProbedMedia, SUPPORTED_EXTENSIONS, probe_video
from app.services.project_store import add_media, project_exists


CHUNK_BYTES = 1024 * 1024


class StoragePathError(RuntimeError):
    """A database path did not resolve inside the managed workspace."""


def managed_path(relative_path: str, *, must_exist: bool = False) -> Path:
    """Resolve a database path and reject absolute/traversal/symlink escapes."""
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise StoragePathError("Stored media path is invalid.")
    root = settings.workspace_dir.resolve(strict=True)
    candidate = (root / Path(*relative.parts)).resolve(strict=must_exist)
    if not candidate.is_relative_to(root):
        raise StoragePathError("Stored media path is outside the managed workspace.")
    return candidate


def relative_path(path: Path) -> str:
    root = settings.workspace_dir.resolve(strict=True)
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise StoragePathError("File path is outside the managed workspace.")
    return resolved.relative_to(root).as_posix()


def managed_directory(relative: str) -> Path:
    """Create a directory below the workspace after checking symlink containment."""
    path_parts = PurePosixPath(relative)
    if path_parts.is_absolute() or not path_parts.parts or any(part in {"", ".", ".."} for part in path_parts.parts):
        raise StoragePathError("Managed directory path is invalid.")
    root = settings.workspace_dir.resolve(strict=True)
    directory = root.joinpath(*path_parts.parts)
    if not directory.resolve(strict=False).is_relative_to(root):
        raise StoragePathError("Managed directory resolves outside the workspace.")
    directory.mkdir(parents=True, exist_ok=True)
    resolved = directory.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise StoragePathError("Managed directory resolves outside the workspace.")
    return resolved


def display_filename(filename: str | None) -> str:
    raw = (filename or "video").replace("\\", "/").split("/")[-1]
    raw = "".join(character for character in raw if character >= " " and character != "\x7f").strip()
    if not raw or raw in {".", ".."}:
        raw = "video"
    return raw[:240]


def safe_display_filename(filename: str | None) -> tuple[str, str]:
    raw = display_filename(filename)
    extension = Path(raw).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise MediaValidationError(
            "Unsupported file type. Choose an MP4, MOV, MKV, AVI, or WebM video."
        )
    return raw, extension


def _upload_limit_error() -> MediaValidationError:
    limit = settings.max_upload_bytes
    readable_limit = f"{limit / 1024**3:.1f} GiB" if limit >= 1024**3 else f"{limit / 1024**2:.1f} MiB"
    return MediaValidationError(f"File exceeds the configured per-file upload limit of {readable_limit}.")


def import_upload(project_id: str, upload: UploadFile) -> MediaOut:
    """Stream one uploaded file, probe it, then commit a private managed copy."""
    if not project_exists(project_id):
        raise LookupError("Project not found.")
    display_name, extension = safe_display_filename(upload.filename)
    if upload.size is not None and upload.size > settings.max_upload_bytes:
        raise _upload_limit_error()
    media_id = str(uuid4())
    settings.ensure_directories()
    managed_directory(f"projects/{project_id}")
    source_dir = managed_directory(f"projects/{project_id}/sources")
    incoming_dir = managed_directory("temp/uploads")
    staged = incoming_dir / f"{uuid4().hex}.upload.part"
    final_path = source_dir / f"{media_id}{extension}"
    size_bytes = 0

    try:
        with staged.open("xb") as destination:
            while True:
                chunk = upload.file.read(CHUNK_BYTES)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > settings.max_upload_bytes:
                    raise _upload_limit_error()
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())

        if size_bytes == 0:
            raise MediaValidationError("The selected file is empty.")

        metadata = probe_video(staged)
        # The source upload is copied to app-managed storage under a random ID.
        # The user's original local file is never opened by path or modified.
        if final_path.exists():
            raise FileExistsError("A managed destination already exists; import was not allowed to overwrite it.")
        os.rename(staged, final_path)
        try:
            result = add_media(
                media_id=media_id,
                project_id=project_id,
                original_filename=display_name,
                source_relative_path=relative_path(final_path),
                size_bytes=size_bytes,
                metadata=metadata,
            )
        except Exception:
            final_path.unlink(missing_ok=True)
            raise
        return result
    finally:
        staged.unlink(missing_ok=True)
        upload.file.close()
