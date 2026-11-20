from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path
import subprocess

import pytest

from fastapi.testclient import TestClient

from app.core.config import settings
from app.services.media_validation import MediaToolError, MediaValidationError, probe_video
from conftest import generate_video


def create_project(client: TestClient) -> str:
    response = client.post("/api/projects", json={"name": "Synthetic test project"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload_one(client: TestClient, project_id: str, path: Path, *, name: str | None = None):
    with path.open("rb") as source:
        return client.post(
            f"/api/projects/{project_id}/media",
            files={"files": (name or path.name, source, "application/octet-stream")},
        )


def test_ffprobe_extracts_real_video_and_audio_metadata(tmp_path: Path, workspace: Path) -> None:
    source = generate_video(tmp_path / "generated.mp4", audio=True, duration=1.5)
    metadata = probe_video(source)

    assert metadata.duration_seconds == 1.5
    assert (metadata.width, metadata.height) == (320, 180)
    assert metadata.frame_rate_decimal == 24
    assert metadata.video_codec == "h264"
    assert metadata.audio_codec == "aac"
    assert metadata.has_audio is True
    assert "mp4" in metadata.container_format


@pytest.mark.parametrize(
    ("extension", "expected_container"),
    [(".mp4", "mp4"), (".mov", "mov"), (".mkv", "matroska"), (".avi", "avi"), (".webm", "webm")],
)
def test_common_containers_are_probeable(tmp_path: Path, workspace: Path, extension: str, expected_container: str) -> None:
    media = generate_video(tmp_path / f"synthetic{extension}", audio=True, duration=1)
    result = probe_video(media)
    assert expected_container in result.container_format
    assert result.duration_seconds > 0
    assert result.width == 320 and result.height == 180


def test_ffprobe_rejects_corrupt_video(tmp_path: Path, workspace: Path) -> None:
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"this is not a video container")
    try:
        probe_video(corrupt)
    except MediaValidationError as error:
        assert "corrupt or unsupported" in str(error)
    else:
        raise AssertionError("Corrupt media was accepted.")


def test_ffprobe_rejects_file_without_video_stream(tmp_path: Path, workspace: Path) -> None:
    audio_only = tmp_path / "audio.mp4"
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac", str(audio_only)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    try:
        probe_video(audio_only)
    except MediaValidationError as error:
        assert "no video stream" in str(error)
    else:
        raise AssertionError("Audio-only media was accepted as video.")


def test_ffprobe_reports_missing_source_file(tmp_path: Path, workspace: Path) -> None:
    try:
        probe_video(tmp_path / "missing.mp4")
    except FileNotFoundError as error:
        assert "missing" in str(error).lower()
    else:
        raise AssertionError("A missing file was accepted.")


def test_missing_ffprobe_has_setup_error(tmp_path: Path, monkeypatch, workspace: Path) -> None:
    media = generate_video(tmp_path / "present.mp4", audio=False)
    monkeypatch.setattr(settings, "ffprobe_path", "clipra-no-such-ffprobe.exe")
    try:
        probe_video(media)
    except MediaToolError as error:
        assert "FFprobe could not be started" in str(error)
    else:
        raise AssertionError("A missing FFprobe executable was ignored.")


def test_multi_upload_is_independent_and_preserves_user_source(client: TestClient, tmp_path: Path, workspace: Path) -> None:
    project_id = create_project(client)
    valid = generate_video(tmp_path / "owned-original.mp4", audio=True)
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"not media")
    original_hash = hashlib.sha256(valid.read_bytes()).hexdigest()
    original_size = valid.stat().st_size

    with valid.open("rb") as valid_file, corrupt.open("rb") as corrupt_file:
        response = client.post(
            f"/api/projects/{project_id}/media",
            files=[
                ("files", ("..\\outside\\owned-original.mp4", valid_file, "video/mp4")),
                ("files", ("broken.mp4", corrupt_file, "video/mp4")),
                ("files", ("notes.txt", b"not a video", "text/plain")),
            ],
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["imported"]) == 1
    assert len(payload["failed"]) == 2
    assert "corrupt or unsupported" in payload["failed"][0]["error"]
    assert "Unsupported file type" in payload["failed"][1]["error"]
    media = payload["imported"][0]
    assert media["original_filename"] == "owned-original.mp4"
    assert media["size_bytes"] == original_size
    assert media["audio_codec"] == "aac"
    assert media["has_audio"] is True
    assert media["duration_seconds"] > 1.4
    assert valid.stat().st_size == original_size
    assert hashlib.sha256(valid.read_bytes()).hexdigest() == original_hash

    project = client.get(f"/api/projects/{project_id}").json()
    assert project["media_count"] == 1
    assert project["media"][0]["id"] == media["id"]
    assert settings.database_path.is_file()


def test_upload_limit_is_enforced_without_registering_partial_media(client: TestClient, tmp_path: Path, monkeypatch, workspace: Path) -> None:
    project_id = create_project(client)
    valid = generate_video(tmp_path / "too-large.mp4", audio=False)
    monkeypatch.setattr(settings, "max_upload_bytes", 100)

    response = upload_one(client, project_id, valid)
    assert response.status_code == 200
    payload = response.json()
    assert payload["imported"] == []
    assert "upload limit" in payload["failed"][0]["error"]
    assert client.get(f"/api/projects/{project_id}").json()["media_count"] == 0
    assert list((settings.temp_dir / "uploads").glob("*.part")) == []


def test_source_stream_supports_ranges_and_returns_416(client: TestClient, tmp_path: Path, workspace: Path) -> None:
    project_id = create_project(client)
    source = generate_video(tmp_path / "stream.mp4", audio=False)
    upload = upload_one(client, project_id, source)
    media = upload.json()["imported"][0]

    partial = client.get(f"/api/media/{media['id']}/stream", headers={"Range": "bytes=0-127"})
    assert partial.status_code == 206
    assert partial.headers["content-range"].startswith("bytes 0-127/")
    assert len(partial.content) == 128
    assert partial.headers["accept-ranges"] == "bytes"

    suffix = client.get(f"/api/media/{media['id']}/stream", headers={"Range": "bytes=-64"})
    assert suffix.status_code == 206
    assert len(suffix.content) == 64

    invalid = client.get(f"/api/media/{media['id']}/stream", headers={"Range": "bytes=999999999-"})
    assert invalid.status_code == 416


def test_missing_managed_file_returns_clear_gone_response(client: TestClient, tmp_path: Path, workspace: Path) -> None:
    project_id = create_project(client)
    source = generate_video(tmp_path / "will-go-missing.mp4", audio=False)
    media = upload_one(client, project_id, source).json()["imported"][0]
    managed_source = settings.projects_dir / project_id / "sources" / f"{media['id']}.mp4"
    managed_source.unlink()

    response = client.get(f"/api/media/{media['id']}/stream")
    assert response.status_code == 410
    assert "missing" in response.json()["detail"].lower()


def test_path_traversal_in_database_is_rejected(client: TestClient, tmp_path: Path, workspace: Path) -> None:
    project_id = create_project(client)
    source = generate_video(tmp_path / "safe.mp4", audio=False)
    media = upload_one(client, project_id, source).json()["imported"][0]
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute("UPDATE media SET source_relative_path = ? WHERE id = ?", ("../../outside.mp4", media["id"]));
    response = client.get(f"/api/media/{media['id']}/stream")
    assert response.status_code == 500
    assert "workspace security" in response.json()["detail"]


def test_preview_fallback_is_separate_and_range_streamable(client: TestClient, tmp_path: Path, workspace: Path) -> None:
    project_id = create_project(client)
    source = generate_video(tmp_path / "legacy.avi", audio=True)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    media = upload_one(client, project_id, source).json()["imported"][0]

    response = client.post(f"/api/media/{media['id']}/preview")
    assert response.status_code == 200, response.text
    preview_media = response.json()["media"]
    assert preview_media["preview_status"] == "ready"
    assert "source was not changed" in response.json()["message"]
    assert source.exists()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash

    source_path = settings.projects_dir / project_id / "sources" / f"{media['id']}.avi"
    preview_path = settings.projects_dir / project_id / "previews" / f"{media['id']}.mp4"
    assert source_path != preview_path
    assert source_path.is_file() and preview_path.is_file()
    proxy_metadata = probe_video(preview_path)
    assert proxy_metadata.video_codec == "h264"
    assert "mp4" in proxy_metadata.container_format

    partial = client.get(f"/api/media/{media['id']}/preview/stream", headers={"Range": "bytes=0-99"})
    assert partial.status_code == 206
    assert len(partial.content) == 100


def test_preview_failure_is_reported_and_saved(client: TestClient, tmp_path: Path, monkeypatch, workspace: Path) -> None:
    project_id = create_project(client)
    source = generate_video(tmp_path / "preview-failure.mp4", audio=False)
    media = upload_one(client, project_id, source).json()["imported"][0]
    monkeypatch.setattr(settings, "ffmpeg_path", "clipra-no-such-ffmpeg.exe")

    response = client.post(f"/api/media/{media['id']}/preview")
    assert response.status_code == 422
    assert "FFmpeg could not be started" in response.json()["detail"]
    detail = client.get(f"/api/projects/{project_id}").json()
    saved = next(item for item in detail["media"] if item["id"] == media["id"])
    assert saved["preview_status"] == "failed"
    assert "FFmpeg" in saved["preview_error"]
