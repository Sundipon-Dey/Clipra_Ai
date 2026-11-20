"""On-demand, non-destructive browser playback proxy generation."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from threading import Lock
from uuid import uuid4

from app.core.config import settings
from app.services.project_store import get_media, get_media_record, update_preview
from app.services.storage import managed_directory, managed_path, relative_path


_preview_locks: dict[str, Lock] = {}
_locks_guard = Lock()


class PreviewError(RuntimeError):
    """The browser-compatible playback copy could not be created."""


def _lock_for(media_id: str) -> Lock:
    with _locks_guard:
        return _preview_locks.setdefault(media_id, Lock())


def create_preview(media_id: str):
    """Create a separate H.264/AAC MP4 proxy without touching the source."""
    record = get_media_record(media_id)
    if record is None:
        raise LookupError("Media item not found.")
    with _lock_for(media_id):
        record = get_media_record(media_id)
        if record["preview_status"] == "ready" and record["preview_relative_path"]:
            try:
                existing = managed_path(record["preview_relative_path"], must_exist=True)
            except (OSError, ValueError):
                existing = None
            if existing and existing.is_file() and existing.stat().st_size > 0:
                return get_media(media_id)

        source = managed_path(record["source_relative_path"], must_exist=True)
        if not source.is_file():
            raise FileNotFoundError("The imported source video is missing from the managed workspace.")
        tool = settings.ffmpeg_path or shutil.which("ffmpeg")
        if not tool:
            message = "FFmpeg was not found. Install FFmpeg and add its bin folder to PATH."
            update_preview(media_id, status="failed", error=message)
            raise PreviewError(message)

        preview_dir = managed_directory(f"projects/{record['project_id']}/previews")
        destination = preview_dir / f"{media_id}.mp4"
        temporary = preview_dir / f".{media_id}.{uuid4().hex}.partial.mp4"
        relative_destination = relative_path(destination)
        update_preview(media_id, status="processing", error=None)

        command = [
            tool,
            "-hide_banner", "-v", "error", "-nostdin",
            "-i", str(source),
            "-map", "0:v:0",
            "-map", "0:a:0?",
            "-sn", "-dn",
            "-vf", "scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "27", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart",
            "-f", "mp4", "-n", str(temporary),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=settings.preview_timeout_seconds,
                check=False,
            )
            if completed.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
                details = (completed.stderr or "FFmpeg produced no preview file.").strip()
                details = " ".join(details.split())[-500:]
                raise PreviewError(f"FFmpeg could not create a playback preview. {details}")
            if destination.exists():
                # Never overwrite any existing generated or user file.
                raise PreviewError("A preview file already exists and was not overwritten.")
            temporary.rename(destination)
            update_preview(
                media_id,
                status="ready",
                relative_path=relative_destination,
                error=None,
            )
            return get_media(media_id)
        except subprocess.TimeoutExpired as error:
            message = "Preview generation exceeded the configured time limit."
            update_preview(media_id, status="failed", error=message)
            raise PreviewError(message) from error
        except FileNotFoundError as error:
            message = "FFmpeg could not be started. Check the FFmpeg installation and configured path."
            update_preview(media_id, status="failed", error=message)
            raise PreviewError(message) from error
        except (OSError, PreviewError) as error:
            message = str(error) or "Preview generation failed."
            update_preview(media_id, status="failed", error=message[:500])
            raise PreviewError(message) from error
        finally:
            temporary.unlink(missing_ok=True)

