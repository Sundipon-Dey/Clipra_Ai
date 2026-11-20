"""Explicit-consent, image-only Gemini focal-point recommendations."""

from __future__ import annotations

import json
import logging
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from google import genai
from google.genai import errors, types

from app.core.config import settings
from app.services.clip_store import complete_framing, fail_framing, get_clip
from app.services.project_store import get_media_record
from app.services.storage import StoragePathError, managed_directory, managed_path

logger = logging.getLogger(__name__)


class FramingFailure(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def validate_focal_points(value: Any, *, start: float, end: float) -> list[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise FramingFailure("malformed_response", "Gemini returned invalid focal-point data.") from exc
    if not isinstance(value, dict) or not isinstance(value.get("focal_points"), list):
        raise FramingFailure("malformed_response", "Gemini returned an unexpected focal-point response.")
    points = []
    for point in value["focal_points"][:8]:
        if not isinstance(point, dict):
            continue
        t, x, y = point.get("time_seconds"), point.get("x"), point.get("y")
        confidence = point.get("confidence")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (t, x, y)):
            continue
        if not start <= t <= end or not 0 <= x <= 1 or not 0 <= y <= 1:
            continue
        if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            confidence = None
        points.append({"time_seconds": round(float(t), 3), "x": float(x), "y": float(y), "confidence": float(confidence) if confidence is not None else None})
    if not points:
        raise FramingFailure("invalid_focal_points", "Gemini did not return any usable focal points for this clip.")
    points.sort(key=lambda p: p["time_seconds"])
    return points


def _extract_frames(source: Path, clip: dict) -> tuple[Path, list[Path]]:
    if not settings.ffmpeg_path:
        raise FramingFailure("ffmpeg_unavailable", "FFmpeg is not configured, so framing frames could not be extracted.")
    settings.ensure_directories()
    directory = managed_directory(f"temp/framing/{clip['id']}-{uuid4().hex}")
    duration = clip["end_seconds"] - clip["start_seconds"]
    timestamps = [clip["start_seconds"] + duration * ratio for ratio in (0.2, 0.5, 0.8)]
    files = []
    try:
        for index, seconds in enumerate(timestamps):
            output = directory / f"frame-{index}.jpg"
            command = [settings.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", f"{seconds:.3f}", "-i", str(source), "-frames:v", "1", "-vf", "scale='min(640,iw)':-2", "-q:v", "5", "-f", "image2", "-n", str(output)]
            try:
                subprocess.run(command, check=True, capture_output=True, timeout=settings.framing_extract_timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                raise FramingFailure("frame_timeout", "Frame extraction timed out. You can still edit this clip without Smart Crop.") from exc
            except (subprocess.CalledProcessError, OSError) as exc:
                raise FramingFailure("frame_extraction_failed", "A preview frame could not be extracted. You can still edit this clip without Smart Crop.") from exc
            if not output.is_file() or output.stat().st_size == 0:
                raise FramingFailure("frame_extraction_failed", "FFmpeg returned an empty preview frame.")
            if output.stat().st_size > settings.framing_max_frame_bytes:
                raise FramingFailure("frame_too_large", "An extracted frame exceeded the configured safe upload limit.")
            files.append(output)
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        if directory.exists():
            logger.warning("Temporary framing extraction cleanup is pending for clip %s", clip["id"])
        raise
    return directory, files


def _recommend(clip: dict, files: list[Path]) -> list[dict]:
    if not settings.gemini_api_key:
        raise FramingFailure("not_configured", "Gemini is not configured. The editor remains available without it.")
    from google.genai import types
    import base64

    duration = clip["end_seconds"] - clip["start_seconds"]
    images = []
    for path in files:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        images.append({"type": "image", "data": encoded, "mime_type": "image/jpeg"})
    client = genai.Client(api_key=settings.gemini_api_key, http_options=types.HttpOptions(
        api_version="v1beta", timeout=settings.gemini_timeout_seconds * 1000,
        retry_options=types.HttpRetryOptions(attempts=1),
    ))
    try:
        response = client.interactions.create(
            model=settings.gemini_model,
            input=[{"type": "text", "text": (
                "These are three still frames sampled in order from one video clip. For vertical 9:16 framing, "
                "identify the main subject/action focal point in each frame. Return source-frame normalized x and y "
                "coordinates from 0 to 1, with 0,0 at top-left. Timestamp each point in absolute source-video seconds. "
                "Do not invent off-screen subjects. Return 1-3 points in strict JSON. Clip bounds are "
                f"{clip['start_seconds']:.3f} to {clip['end_seconds']:.3f} seconds (duration {duration:.3f})."
            )}, *images],
            response_format={"type": "text", "mime_type": "application/json", "schema": {
                "type": "object", "properties": {"focal_points": {"type": "array", "items": {
                    "type": "object", "properties": {"time_seconds": {"type": "number"}, "x": {"type": "number"}, "y": {"type": "number"}, "confidence": {"type": "number"}},
                    "required": ["time_seconds", "x", "y"], "additionalProperties": False,
                }}}, "required": ["focal_points"], "additionalProperties": False,
            }},
            generation_config={"temperature": 0, "max_output_tokens": 1024},
        )
        raw = getattr(response, "output_text", None)
        return validate_focal_points(raw, start=clip["start_seconds"], end=clip["end_seconds"])
    except FramingFailure:
        raise
    except errors.APIError as exc:
        code = getattr(exc, "status_code", getattr(exc, "code", None))
        if code == 429:
            raise FramingFailure("quota_or_rate_limit", "Gemini quota or rate limit was reached. Smart Crop is optional; adjust framing manually or try later.") from exc
        if code in (401, 403):
            raise FramingFailure("authentication", "Gemini rejected the configured key or model access. Manual framing remains available.") from exc
        if code == 504:
            raise FramingFailure("timeout", "Gemini framing timed out. Manual framing remains available; no automatic retry was made.") from exc
        raise FramingFailure("gemini_api_error", f"Gemini framing failed (HTTP {code}). Manual framing remains available.") from exc
    except (TimeoutError, OSError) as exc:
        raise FramingFailure("timeout_or_network", "Gemini could not be reached or timed out. Manual framing remains available.") from exc
    except Exception as exc:
        logger.warning("Framing recommendation failed (%s)", type(exc).__name__)
        raise FramingFailure("gemini_request_failed", "The framing recommendation failed. Manual framing remains available.") from exc
    finally:
        try:
            client.close()
        except Exception:
            logger.warning("Framing Gemini client close failed")


def process_framing(clip_id: str) -> None:
    clip = get_clip(clip_id)
    directory = None
    try:
        if clip is None or clip["framing_status"] != "pending":
            return
        media = get_media_record(clip["media_id"])
        if media is None:
            raise FramingFailure("media_missing", "The source video record is missing.")
        try:
            source = managed_path(media["source_relative_path"], must_exist=True)
        except (FileNotFoundError, StoragePathError, ValueError) as exc:
            raise FramingFailure("source_missing", "The managed source video is missing or failed a storage security check.") from exc
        if not source.is_file():
            raise FramingFailure("source_missing", "The managed source video is missing.")
        directory, frames = _extract_frames(source, clip)
        points = _recommend(clip, frames)
        complete_framing(clip_id, model=settings.gemini_model, points=points)
    except FramingFailure as exc:
        fail_framing(clip_id, code=exc.code, message=exc.message)
    except Exception as exc:
        logger.warning("Unexpected framing failure (%s)", type(exc).__name__)
        fail_framing(clip_id, code="framing_failed", message="Smart Crop recommendation failed. Manual framing remains available.")
    finally:
        if directory is not None:
            root = settings.temp_dir.resolve(strict=True)
            if directory.resolve(strict=False).is_relative_to(root) and directory.name.startswith(clip_id + "-"):
                shutil.rmtree(directory, ignore_errors=True)
                if directory.exists():
                    logger.warning("Temporary framing directory cleanup is pending for clip %s", clip_id)
