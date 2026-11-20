"""Bounded, validated image storage for split-screen clip layouts."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import settings
from app.db.database import connect
from app.services.clip_store import get_clip
from app.services.project_store import utc_now
from app.services.storage import display_filename, managed_directory, relative_path

CHUNK_BYTES = 1024 * 1024
FORMATS = {
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".webp": ("image/webp", b"RIFF"),
}
MAX_DIMENSION = 8192
MAX_PIXELS = 40_000_000


class LayoutImageError(ValueError):
    pass


def _probe(path: Path) -> tuple[int, int]:
    command = [settings.ffprobe_path or "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", str(path)]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=settings.ffprobe_timeout_seconds, shell=False)
        stream = json.loads(result.stdout)["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
        raise LayoutImageError("The image could not be decoded or inspected.") from exc
    if width < 1 or height < 1 or width > MAX_DIMENSION or height > MAX_DIMENSION or width * height > MAX_PIXELS:
        raise LayoutImageError("Image dimensions exceed the supported limit of 8192 pixels per side and 40 megapixels.")
    # Probe metadata alone does not prove the full image decodes; ask FFmpeg to decode one frame.
    decode = [settings.ffmpeg_path or "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-frames:v", "1", "-f", "null", "-"]
    try:
        subprocess.run(decode, check=True, capture_output=True, timeout=settings.ffprobe_timeout_seconds, shell=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise LayoutImageError("The image is malformed or uses an unsupported encoding.") from exc
    return width, height


def upload_layout_image(clip_id: str, upload: UploadFile) -> dict:
    clip = get_clip(clip_id)
    if not clip:
        raise LookupError("Draft clip not found.")
    filename = display_filename(upload.filename)
    extension = Path(filename).suffix.lower()
    if extension not in FORMATS:
        raise LayoutImageError("Choose a PNG, JPG, or WebP image.")
    content_type, signature = FORMATS[extension]
    if upload.size is not None and upload.size > settings.max_layout_image_bytes:
        raise LayoutImageError("Image exceeds the configured layout-image size limit.")

    settings.ensure_directories()
    staging_dir = managed_directory("temp/layout-images")
    asset_dir = managed_directory(f"projects/{clip['project_id']}/layout-images")
    token = uuid4().hex
    staging = staging_dir / f"{token}.upload.part"
    asset_id = str(uuid4())
    final = asset_dir / f"{asset_id}{extension}"
    size = 0
    first = b""
    try:
        with staging.open("xb") as output:
            while True:
                chunk = upload.file.read(CHUNK_BYTES)
                if not chunk:
                    break
                if not first:
                    first = chunk[:12]
                size += len(chunk)
                if size > settings.max_layout_image_bytes:
                    raise LayoutImageError("Image exceeds the configured layout-image size limit.")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        signature_valid = first.startswith(signature)
        if extension == ".webp":
            signature_valid = len(first) >= 12 and first.startswith(b"RIFF") and first[8:12] == b"WEBP"
        if not size or not signature_valid:
            raise LayoutImageError("The image contents do not match its PNG, JPG, or WebP file type.")
        width, height = _probe(staging)
        if final.exists():
            raise FileExistsError("Refusing to overwrite an existing layout image.")
        os.rename(staging, final)
        now = utc_now()
        try:
            with connect() as db:
                db.execute("INSERT INTO clip_layout_assets(id,clip_id,relative_path,original_filename,content_type,size_bytes,width,height,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                           (asset_id, clip_id, relative_path(final), filename[:240], content_type, size, width, height, now))
        except Exception:
            final.unlink(missing_ok=True)
            raise
        return get_layout_image(asset_id, clip_id) or {}
    finally:
        staging.unlink(missing_ok=True)
        upload.file.close()


def get_layout_image(asset_id: str, clip_id: str | None = None) -> dict | None:
    with connect() as db:
        if clip_id:
            row = db.execute("SELECT * FROM clip_layout_assets WHERE id=? AND clip_id=?", (asset_id, clip_id)).fetchone()
        else:
            row = db.execute("SELECT * FROM clip_layout_assets WHERE id=?", (asset_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["image_url"] = f"/api/layout-images/{asset_id}"
    return result


def list_layout_images(clip_id: str) -> list[dict]:
    with connect() as db:
        ids = [row[0] for row in db.execute("SELECT id FROM clip_layout_assets WHERE clip_id=? ORDER BY created_at DESC", (clip_id,)).fetchall()]
    return [item for asset_id in ids if (item := get_layout_image(asset_id, clip_id)) is not None]

