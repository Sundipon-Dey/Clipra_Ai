from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.main import app


def generate_video(path: Path, *, audio: bool = True, duration: float = 1.5) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.fail("FFmpeg is required for synthetic media tests.")
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=24:duration={duration}",
    ]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=900:sample_rate=44100:duration={duration}", "-shortest"]
    if path.suffix.lower() == ".avi":
        command += ["-c:v", "mpeg4", "-q:v", "8"]
        if audio:
            command += ["-c:a", "pcm_s16le"]
    elif path.suffix.lower() == ".webm":
        command += ["-c:v", "libvpx", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "300k"]
        if audio:
            command += ["-c:a", "libopus", "-b:a", "64k"]
    else:
        command += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
        if audio:
            command += ["-c:a", "aac", "-b:a", "64k"]
    command.append(str(path))
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    return path


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "workspace_dir", tmp_path / "managed")
    monkeypatch.setattr(settings, "max_upload_bytes", 1024 * 1024 * 100)
    monkeypatch.setattr(settings, "max_files_per_import", 20)
    monkeypatch.setattr(settings, "ffprobe_path", shutil.which("ffprobe"))
    monkeypatch.setattr(settings, "ffmpeg_path", shutil.which("ffmpeg"))
    return settings.workspace_dir


@pytest.fixture
def client(workspace: Path):
    with TestClient(app) as test_client:
        yield test_client
