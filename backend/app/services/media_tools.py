"""Resolve FFmpeg utilities with explicit configuration taking priority."""

from __future__ import annotations

import shutil

from app.core.config import settings


def resolve_ffmpeg() -> str | None:
    return settings.ffmpeg_path or shutil.which("ffmpeg")


def resolve_ffprobe() -> str | None:
    return settings.ffprobe_path or shutil.which("ffprobe")
