"""FFprobe-backed media inspection. No metadata is inferred from filenames."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from app.core.config import settings


SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


class MediaValidationError(ValueError):
    """The uploaded file is not a supported video with readable metadata."""


class MediaToolError(RuntimeError):
    """An external media tool is missing or failed unexpectedly."""


@dataclass(frozen=True)
class ProbedMedia:
    duration_seconds: float
    width: int
    height: int
    frame_rate: str | None
    frame_rate_decimal: float | None
    video_codec: str
    audio_codec: str | None
    has_audio: bool
    container_format: str


def _rate_value(value: Any) -> tuple[str | None, float | None]:
    if not isinstance(value, str) or not value or value in {"0/0", "N/A"}:
        return None, None
    try:
        numeric = float(Fraction(value))
    except (ValueError, ZeroDivisionError, OverflowError):
        return value, None
    if not math.isfinite(numeric) or numeric <= 0:
        return value, None
    return value, numeric


def probe_video(path: Path) -> ProbedMedia:
    if not path.is_file():
        raise FileNotFoundError("The stored video file is missing.")

    tool = settings.ffprobe_path or shutil.which("ffprobe")
    if not tool:
        raise MediaToolError("FFprobe was not found. Install FFmpeg and add its bin folder to PATH.")

    command = [
        tool,
        "-v", "error",
        "-show_streams",
        "-show_format",
        "-of", "json",
        str(path.resolve()),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.ffprobe_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise MediaValidationError("FFprobe took too long to read this file.") from error
    except FileNotFoundError as error:
        raise MediaToolError("FFprobe could not be started. Check the FFmpeg installation and configured path.") from error

    if completed.returncode != 0:
        raise MediaValidationError("FFprobe could not read this file. It may be corrupt or unsupported.")
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise MediaValidationError("FFprobe returned invalid media metadata.") from error

    streams = data.get("streams")
    if not isinstance(streams, list):
        raise MediaValidationError("No readable media streams were found.")
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    if not video_streams:
        raise MediaValidationError("This file has no video stream.")

    video = video_streams[0]
    try:
        width = int(video["width"])
        height = int(video["height"])
    except (KeyError, TypeError, ValueError) as error:
        raise MediaValidationError("FFprobe did not return valid video dimensions.") from error
    if width <= 0 or height <= 0:
        raise MediaValidationError("The video dimensions are invalid.")

    format_data = data.get("format") or {}
    duration_value = format_data.get("duration") or video.get("duration")
    try:
        duration = float(duration_value)
    except (TypeError, ValueError) as error:
        raise MediaValidationError("FFprobe did not return a valid video duration.") from error
    if not math.isfinite(duration) or duration <= 0:
        raise MediaValidationError("The video duration must be greater than zero.")

    rate, rate_decimal = _rate_value(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    video_codec = video.get("codec_name")
    container_format = format_data.get("format_name")
    if not video_codec or not container_format:
        raise MediaValidationError("FFprobe returned incomplete codec or container information.")

    return ProbedMedia(
        duration_seconds=duration,
        width=width,
        height=height,
        frame_rate=rate,
        frame_rate_decimal=rate_decimal,
        video_codec=str(video_codec),
        audio_codec=str(audio_streams[0].get("codec_name")) if audio_streams and audio_streams[0].get("codec_name") else None,
        has_audio=bool(audio_streams),
        container_format=str(container_format),
    )
