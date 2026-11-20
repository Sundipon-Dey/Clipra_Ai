from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.services.project_store import get_media_record
from app.db.database import connect, initialize_database
from app.services.render_pipeline import build_ass, render
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


def test_one_word_ass_keeps_supported_punctuation_rule_and_timing():
    clip = {"start_seconds": 2.0}
    track = {"style": {"font_family": "Arial", "font_weight": 700, "font_size": 62, "text_color": "#FFFFFF", "highlight_color": "#E8FF4D", "outline_color": "#000000", "outline_width": 3, "shadow_offset": 0, "background_color": "#000000", "background_opacity": 0, "alignment": "center", "animation": "none", "animation_ms": 0},
             "grouping": {"display_mode": "one_word"}, "position_x": .5, "position_y": .76, "timing_offset_seconds": 0,
             "segments": [{"start_seconds": .1, "end_seconds": 1.0, "generated_text": "Hello, world.", "words": [
                 {"start_seconds": .1, "end_seconds": .4, "text": "Hello,"}, {"start_seconds": .5, "end_seconds": .9, "text": "world."}]}]}
    ass = build_ass(track, clip)
    assert "Hello," not in ass and "world." not in ass
    assert "Hello" in ass and "world" in ass
    assert "0:00:00.10" in ass


def test_phrase_ass_matches_active_word_preset_colors_pop_and_shadow_without_outline():
    track = {"style": {"font_family": "Arial", "font_weight": 700, "font_size": 62, "text_color": "#FFFFFF", "highlight_color": "#00FFFF", "outline_color": "#000000", "outline_width": 3, "shadow_color": "#FF008C", "shadow_offset": 4, "background_color": "#000000", "background_opacity": 0, "alignment": "center", "animation": "pop_karaoke", "animation_ms": 120},
             "grouping": {"display_mode": "phrase"}, "position_x": .5, "position_y": .76, "timing_offset_seconds": 0,
             "segments": [{"start_seconds": .1, "end_seconds": .9, "generated_text": "Hello world", "words": [
                 {"start_seconds": .1, "end_seconds": .5, "text": "Hello"}, {"start_seconds": .5, "end_seconds": .9, "text": "world"}]}]}
    ass = build_ass(track, {"start_seconds": 0})
    dialogue = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogue) == 2
    assert r"{\c&H00FFFF00&\fscx72\fscy72\t(0,120,\fscx128\fscy128)" in dialogue[0]
    assert r"{\c&H00FFFF00&\fscx72\fscy72\t(0,120,\fscx128\fscy128)" in dialogue[1]
    assert r"{\c&H00FFFFFF&\fscx100\fscy100}" in dialogue[0]
    assert r"\k" not in ass
    style_line = next(line for line in ass.splitlines() if line.startswith("Style:"))
    assert style_line.split(",")[10] == "0"
    assert style_line.split(",")[11] == "6.0"
    assert r"\4c&H008C00FF&" in ass


def test_every_caption_animation_pops_the_active_spoken_word():
    for animation, animation_ms in (("none", 0), ("fade", 160), ("pop", 140), ("karaoke", 90), ("pop_karaoke", 120)):
        track = {"style": {"font_family": "Arial", "font_weight": 700, "font_size": 62, "text_color": "#FFFFFF", "highlight_color": "#00FFFF", "outline_color": "#000000", "outline_width": 0, "shadow_color": "#000000", "shadow_offset": 0, "background_color": "#000000", "background_opacity": 0, "alignment": "center", "animation": animation, "animation_ms": animation_ms},
                 "grouping": {"display_mode": "phrase"}, "position_x": .5, "position_y": .76, "timing_offset_seconds": 0,
                 "segments": [{"start_seconds": .1, "end_seconds": .9, "generated_text": "Hello world", "words": [{"start_seconds": .1, "end_seconds": .5, "text": "Hello"}, {"start_seconds": .5, "end_seconds": .9, "text": "world"}]}]}
        dialogue = [line for line in build_ass(track, {"start_seconds": 0}).splitlines() if line.startswith("Dialogue:")]
        assert len(dialogue) == 2, animation
        assert r"\fscx72\fscy72\t(0," in dialogue[0], animation
        assert r"\fscx72\fscy72\t(0," in dialogue[1], animation


def test_plain_caption_override_escapes_ass_controls():
    track = {"style": {"font_family": "Arial", "font_weight": 700, "font_size": 62, "text_color": "#FFFFFF", "highlight_color": "#00FFFF", "outline_color": "#000000", "outline_width": 3, "shadow_offset": 0, "background_color": "#000000", "background_opacity": 0, "alignment": "center", "animation": "none", "animation_ms": 0},
             "grouping": {}, "position_x": .5, "position_y": .76, "timing_offset_seconds": 0,
             "segments": [{"start_seconds": .1, "end_seconds": .9, "override_text": "literal {\\k20} text", "words": []}]}
    ass = build_ass(track, {"start_seconds": 0})
    assert r"literal \{\\k20\} text" in ass


def test_caption_preview_renders_timed_word_colors_through_ffmpeg(client, tmp_path):
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
    render(snapshot, output, preview=True, job_id="caption-timing-fixture", progress_callback=lambda _progress: None)
    assert output.is_file() and output.stat().st_size > 1000
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", str(output)], check=True, capture_output=True, text=True)
    video = json.loads(probe.stdout)["streams"][0]
    assert (video["width"], video["height"]) == (1080, 1920)
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
        assert db.execute("PRAGMA user_version").fetchone()[0] == 8


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


def test_preview_invalidation_export_version_history_and_source_preservation(client, tmp_path, monkeypatch):
    from app.services.render_queue import _run

    media_json = _import_video(client, tmp_path)
    clip_response = client.post(f"/api/media/{media_json['id']}/clips", json={"title": "Versioned", "start_seconds": .1, "end_seconds": 1.3})
    clip = clip_response.json()
    record = get_media_record(media_json["id"])
    source = managed_path(record["source_relative_path"], must_exist=True)
    source_before = source.read_bytes()
    monkeypatch.setattr("app.api.renders.enqueue", _run)

    preview = client.post(f"/api/clips/{clip['id']}/previews")
    assert preview.status_code == 202, preview.text
    first_preview = preview.json()
    assert first_preview["status"] == "completed"
    assert first_preview["current"] is True
    saved_preview = managed_path(get(first_preview["id"])["output_relative_path"], must_exist=True)
    assert saved_preview.is_file()
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", str(saved_preview)], check=True, capture_output=True, text=True)
    video_stream = json.loads(probe.stdout)["streams"][0]
    assert (video_stream["width"], video_stream["height"]) == (1080, 1920)

    changed = client.patch(f"/api/clips/{clip['id']}", json={"fit_background_color": "#334455"})
    assert changed.status_code == 200
    assert client.get(f"/api/render-jobs/{first_preview['id']}").json()["current"] is False
    assert client.post(f"/api/render-jobs/{first_preview['id']}/approve-export", json={"approved": True}).status_code == 409

    second_preview = client.post(f"/api/clips/{clip['id']}/previews").json()
    assert second_preview["status"] == "completed"
    approved = client.post(f"/api/render-jobs/{second_preview['id']}/approve-export", json={"approved": True})
    assert approved.status_code == 202, approved.text
    version_one = approved.json()
    assert version_one["status"] == "completed"
    assert version_one["version_number"] == 1
    assert version_one["config_hash"] == second_preview["config_hash"]
    first_export = managed_path(get(version_one["id"])["output_relative_path"], must_exist=True)
    bytes_v1 = first_export.read_bytes()
    assert len(bytes_v1) > 1000

    # Editing after V1 and approving another fresh preview preserves V1 as-is.
    client.patch(f"/api/clips/{clip['id']}", json={"title": "Versioned again"})
    third_preview = client.post(f"/api/clips/{clip['id']}/previews").json()
    version_two = client.post(f"/api/render-jobs/{third_preview['id']}/approve-export", json={"approved": True}).json()
    assert version_two["status"] == "completed" and version_two["version_number"] == 2
    assert first_export.read_bytes() == bytes_v1
    assert source.read_bytes() == source_before
    history = client.get(f"/api/clips/{clip['id']}/render-jobs").json()
    assert [job["version_number"] for job in history if job["kind"] == "export"] == [2, 1]
    streamed = client.get(f"/api/render-jobs/{version_one['id']}/stream", headers={"Range": "bytes=0-99"})
    assert streamed.status_code == 206 and len(streamed.content) == 100
    assert client.get(version_one["download_url"]).status_code == 200

