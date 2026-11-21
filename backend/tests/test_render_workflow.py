from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.services.project_store import get_media_record
from app.db.database import connect, initialize_database
from app.services.render_pipeline import render
from app.services.render_snapshot import capture
from app.services.render_store import get
from app.services.storage import managed_directory, managed_path
from conftest import generate_video


def _import_video(client, tmp_path: Path):
    video = generate_video(tmp_path / "stage5-source.mp4", duration=1.6)
    project = client.post("/api/projects", json={"name": "Stage 5"}).json()
    with video.open("rb") as stream:
        response = client.post(f"/api/projects/{project['id']}/media", files={"files": (video.name, stream, "video/mp4")})
    assert response.status_code == 200
    return response.json()["imported"][0]


def test_caption_export_uses_editor_chromium_overlay_and_crf18_through_ffmpeg(client, tmp_path, monkeypatch):
    from app.services import render_pipeline

    commands = []
    original_popen = render_pipeline.subprocess.Popen
    def record_command(command, *args, **kwargs):
        commands.append(command)
        return original_popen(command, *args, **kwargs)
    monkeypatch.setattr(render_pipeline.subprocess, "Popen", record_command)
    media_json = _import_video(client, tmp_path)
    media = get_media_record(media_json["id"])
    style = {"font_family": "Arial", "font_weight": 700, "font_size": 62, "text_color": "#FFFFFF", "highlight_color": "#00FFFF", "outline_color": "#000000", "outline_width": 8, "shadow_color": "#FF008C", "shadow_offset": 4, "background_color": "#000000", "background_opacity": 0, "alignment": "center", "animation": "pop_karaoke", "animation_ms": 120}
    track = {"style": style, "grouping": {"display_mode": "phrase"}, "position_x": .5, "position_y": .76, "timing_offset_seconds": 0,
             "segments": [{"start_seconds": .1, "end_seconds": .9, "generated_text": "Hello world", "override_text": None, "words": [
                 {"start_seconds": .1, "end_seconds": .5, "text": "Hello"}, {"start_seconds": .5, "end_seconds": .9, "text": "world"}]}]}
    snapshot = {"clip": {"start_seconds": .1, "end_seconds": 1.3, "framing_mode": "fit", "fit_background_color": "#090a0f", "layout_type": "original"},
                "source_relative_path": media["source_relative_path"], "caption_track": track, "focal_points": []}
    output = managed_directory("temp/rendering") / "caption-timing-fixture.mp4"
    assert not output.exists()
    render(snapshot, output, job_id="caption-export-fixture", progress_callback=lambda _progress: None)
    assert any("-crf" in command and command[command.index("-crf") + 1] == "18" and command[command.index("-preset") + 1] == "medium" for command in commands)
    assert output.is_file() and output.stat().st_size > 1000
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", str(output)], check=True, capture_output=True, text=True)
    video = json.loads(probe.stdout)["streams"][0]
    assert (video["width"], video["height"]) == (1080, 1920)
    caption_frame = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "0.25", "-i", str(output), "-frames:v", "1",
         "-vf", "crop=1080:500:0:1250,format=rgb24", "-f", "rawvideo", "pipe:1"],
        check=True, capture_output=True, timeout=30,
    ).stdout
    assert len(caption_frame) == 1080 * 500 * 3
    assert any(caption_frame[index] > 180 for index in range(0, len(caption_frame), 3)), "Rendered caption pixels should be visible in the transparent composition area."
    assert not (managed_directory("temp/rendering") / "caption-export-fixture-caption-frames").exists(), "Temporary Chromium caption frames should be removed after render."
    output.unlink(missing_ok=True)


def test_schema_v7_migrates_to_split_layout_additions(client):
    # Downgrade the initialized schema's split-layout additions, then run the v7 -> v8 migration.
    with connect() as db:
        db.execute("DROP TABLE clip_layout_assets")
        db.execute("ALTER TABLE clips DROP COLUMN split_layout_json")
        db.execute("ALTER TABLE clips DROP COLUMN layout_type")
        db.execute("PRAGMA user_version=7")
    initialize_database()
    with connect() as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(clips)").fetchall()}
        assert "layout_type" in columns and "split_layout_json" in columns
        assert db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='clip_layout_assets'").fetchone()
        assert db.execute("PRAGMA user_version").fetchone()[0] == 10


def test_original_layout_snapshot_keeps_legacy_shape(client, tmp_path):
    media_json = _import_video(client, tmp_path)
    clip_response = client.post(f"/api/media/{media_json['id']}/clips", json={"title": "Original", "start_seconds": .1, "end_seconds": 1.3})
    assert clip_response.status_code == 201
    snapshot = capture(clip_response.json()["id"])
    assert snapshot is not None
    assert snapshot["clip"].get("layout_type") is None
    assert snapshot["clip"].get("split_layout") is None
    assert "source_frame_rate_decimal" not in snapshot
    assert "layout_image_relative_path" not in snapshot


def test_direct_approved_export_versions_preserve_source_and_prior_exports(client, tmp_path, monkeypatch):
    from app.services.render_queue import _run

    media_json = _import_video(client, tmp_path)
    clip_response = client.post(f"/api/media/{media_json['id']}/clips", json={"title": "Versioned", "start_seconds": .1, "end_seconds": 1.3})
    clip = clip_response.json()
    record = get_media_record(media_json["id"])
    source = managed_path(record["source_relative_path"], must_exist=True)
    source_before = source.read_bytes()
    monkeypatch.setattr("app.api.renders.enqueue", _run)

    assert client.post(f"/api/clips/{clip['id']}/previews").status_code == 404
    assert client.post(f"/api/clips/{clip['id']}/exports", json={"approved": False}).status_code == 400
    assert client.get(f"/api/clips/{clip['id']}/render-jobs").json() == []
    first = client.post(f"/api/clips/{clip['id']}/exports", json={"approved": True})
    assert first.status_code == 202, first.text
    version_one = first.json()
    assert version_one["status"] == "completed" and version_one["version_number"] == 1
    saved_export = managed_path(get(version_one["id"])["output_relative_path"], must_exist=True)
    assert saved_export.is_file()
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", str(saved_export)], check=True, capture_output=True, text=True)
    video_stream = json.loads(probe.stdout)["streams"][0]
    assert (video_stream["width"], video_stream["height"]) == (1080, 1920)
    first_export = managed_path(get(version_one["id"])["output_relative_path"], must_exist=True)
    bytes_v1 = first_export.read_bytes()
    assert len(bytes_v1) > 1000

    # Editing after V1 and exporting again preserves V1 as-is.
    client.patch(f"/api/clips/{clip['id']}", json={"title": "Versioned again"})
    version_two_response = client.post(f"/api/clips/{clip['id']}/exports", json={"approved": True})
    assert version_two_response.status_code == 202, version_two_response.text
    version_two = version_two_response.json()
    assert version_two["status"] == "completed" and version_two["version_number"] == 2
    assert first_export.read_bytes() == bytes_v1
    assert source.read_bytes() == source_before
    history = client.get(f"/api/clips/{clip['id']}/render-jobs").json()
    assert [job["version_number"] for job in history if job["kind"] == "export"] == [2, 1]
    streamed = client.get(f"/api/render-jobs/{version_one['id']}/stream", headers={"Range": "bytes=0-99"})
    assert streamed.status_code == 206 and len(streamed.content) == 100
    assert client.get(version_one["download_url"]).status_code == 200

