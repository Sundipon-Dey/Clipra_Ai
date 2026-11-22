from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.services.clip_store import get_clip
from app.services.layout_image_store import get_layout_image
from app.services.render_store import get as get_render
from app.services.storage import managed_path
from conftest import generate_video


def _import_video(client, tmp_path: Path):
    video = generate_video(tmp_path / "split-source.mp4", duration=1.4, audio=True)
    project = client.post("/api/projects", json={"name": "Split layout"}).json()
    with video.open("rb") as stream:
        result = client.post(f"/api/projects/{project['id']}/media", files={"files": (video.name, stream, "video/mp4")})
    assert result.status_code == 200
    media = result.json()["imported"][0]
    clip = client.post(f"/api/media/{media['id']}/clips", json={"title": "Streamer layout", "start_seconds": .1, "end_seconds": 1.1}).json()
    return media, clip


def _layout():
    return {
        "split_ratio": .42,
        "top": {"source_mode": "same_video", "image_asset_id": None, "solid_color": "#151923", "framing_mode": "crop", "zoom": 1.8, "position_x": .22, "position_y": .37, "fit_background_color": "#112233"},
        "bottom": {"source_mode": "same_video", "image_asset_id": None, "solid_color": "#151923", "framing_mode": "fit", "zoom": 1.25, "position_x": .79, "position_y": .68, "fit_background_color": "#334455"},
    }


def _upload_png(client, clip_id: str, tmp_path: Path):
    path = tmp_path / "facecam.png"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=magenta:s=96x128:d=1", "-frames:v", "1", str(path)], check=True, capture_output=True, timeout=30)
    with path.open("rb") as stream:
        return client.post(f"/api/clips/{clip_id}/layout-images", files={"file": (path.name, stream, "image/png")})


@pytest.mark.parametrize(("extension", "codec", "content_type"), [("jpg", "mjpeg", "image/jpeg"), ("webp", "libwebp", "image/webp")])
def test_layout_image_upload_supports_valid_jpeg_and_webp(client, tmp_path, extension, codec, content_type):
    _, clip = _import_video(client, tmp_path)
    path = tmp_path / f"custom.{extension}"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=cyan:s=96x128:d=1", "-frames:v", "1", "-c:v", codec, str(path)], check=True, capture_output=True, timeout=30)
    with path.open("rb") as stream:
        result = client.post(f"/api/clips/{clip['id']}/layout-images", files={"file": (path.name, stream, content_type)})
    assert result.status_code == 201, result.text
    assert result.json()["content_type"] == content_type


def test_split_settings_are_independent_and_survive_layout_switch(client, tmp_path):
    _, clip = _import_video(client, tmp_path)
    original = client.patch(f"/api/clips/{clip['id']}", json={"framing_mode": "fit", "manual_zoom": 2.2}).json()
    updated = client.patch(f"/api/clips/{clip['id']}", json={"layout_type": "split_streamer_gameplay", "split_layout": _layout()})
    assert updated.status_code == 200, updated.text
    stored = updated.json()
    assert stored["layout_type"] == "split_streamer_gameplay"
    assert stored["split_layout"]["top"]["position_x"] == .22
    assert stored["split_layout"]["bottom"]["position_x"] == .79
    assert stored["framing_mode"] == original["framing_mode"] == "fit"
    assert stored["manual_zoom"] == original["manual_zoom"] == 2.2
    changed_top = _layout()
    changed_top["top"]["zoom"] = 2.4
    changed = client.patch(f"/api/clips/{clip['id']}", json={"split_layout": changed_top}).json()
    assert changed["split_layout"]["top"]["zoom"] == 2.4
    assert changed["split_layout"]["bottom"] == stored["split_layout"]["bottom"]
    reopened = client.patch(f"/api/clips/{clip['id']}", json={"layout_type": "original"}).json()
    assert reopened["layout_type"] == "original"
    assert reopened["split_layout"]["top"]["zoom"] == 2.4
    assert get_clip(clip["id"])["split_layout"]["bottom"]["zoom"] == 1.25


def test_layout_image_upload_is_validated_and_kept_managed(client, tmp_path, monkeypatch):
    from app.core.config import settings

    _, clip = _import_video(client, tmp_path)
    uploaded = _upload_png(client, clip["id"], tmp_path)
    assert uploaded.status_code == 201, uploaded.text
    asset = uploaded.json()
    assert asset["content_type"] == "image/png"
    assert (asset["width"], asset["height"]) == (96, 128)
    image_path = managed_path(get_layout_image(asset["id"], clip["id"])["relative_path"], must_exist=True)
    assert image_path.is_file()
    config = _layout()
    config["top"].update(source_mode="custom_image", image_asset_id=asset["id"])
    saved = client.patch(f"/api/clips/{clip['id']}", json={"layout_type": "split_streamer_gameplay", "split_layout": config})
    assert saved.status_code == 200, saved.text
    assert client.get(asset["image_url"]).status_code == 200
    assert client.patch(f"/api/clips/{clip['id']}", json={"split_layout": {**config, "top": {**config["top"], "image_asset_id": "another-clips-image"}}}).status_code == 422
    bad = client.post(f"/api/clips/{clip['id']}/layout-images", files={"file": ("fake.png", b"not an image", "image/png")})
    assert bad.status_code == 422
    monkeypatch.setattr(settings, "max_layout_image_bytes", 16)
    oversized = client.post(f"/api/clips/{clip['id']}/layout-images", files={"file": ("large.png", b"x" * 100, "image/png")})
    assert oversized.status_code == 422
    assert image_path.exists()


def test_split_renderer_composes_video_twice_or_custom_image_once_with_single_audio(client, tmp_path, monkeypatch):
    from app.services.render_queue import _run

    media, clip = _import_video(client, tmp_path)
    monkeypatch.setattr("app.api.renders.enqueue", _run)
    split = client.patch(f"/api/clips/{clip['id']}", json={"layout_type": "split_streamer_gameplay", "split_layout": _layout()})
    assert split.status_code == 200
    same_video_export = client.post(f"/api/clips/{clip['id']}/exports", json={"approved": True})
    assert same_video_export.status_code == 202, same_video_export.text
    same_video_job = get_render(same_video_export.json()["id"])
    assert same_video_job["status"] == "completed", same_video_job["error_message"]
    same_video_path = managed_path(same_video_job["output_relative_path"], must_exist=True)

    asset = _upload_png(client, clip["id"], tmp_path).json()
    config = _layout()
    config["top"].update(source_mode="custom_image", image_asset_id=asset["id"])
    assert client.patch(f"/api/clips/{clip['id']}", json={"split_layout": config}).status_code == 200
    custom_export_response = client.post(f"/api/clips/{clip['id']}/exports", json={"approved": True})
    assert custom_export_response.status_code == 202, custom_export_response.text
    custom_export = custom_export_response.json()
    assert custom_export["status"] == "completed" and custom_export["version_number"] == 2
    custom_job = get_render(custom_export["id"])
    assert json.loads(custom_job["snapshot_json"])["layout_image_relative_path"]
    export_path = managed_path(get_render(custom_export["id"])["output_relative_path"], must_exist=True)

    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "json", str(export_path)], check=True, capture_output=True, text=True)
    streams = json.loads(probe.stdout)["streams"]
    videos = [stream for stream in streams if stream["codec_type"] == "video"]
    audios = [stream for stream in streams if stream["codec_type"] == "audio"]
    assert len(videos) == 1 and (videos[0]["width"], videos[0]["height"]) == (1080, 1920)
    assert len(audios) == 1
    assert same_video_path.is_file() and export_path.is_file()

    # Replacing the saved image reference cannot remove the image captured by a completed render snapshot.
    next_asset = _upload_png(client, clip["id"], tmp_path).json()
    config["top"]["image_asset_id"] = next_asset["id"]
    assert client.patch(f"/api/clips/{clip['id']}", json={"split_layout": config}).status_code == 200
    retained_path = managed_path(json.loads(custom_job["snapshot_json"])["layout_image_relative_path"], must_exist=True)
    assert retained_path.is_file()


def test_solid_color_top_source_is_persisted_and_rendered(client, tmp_path, monkeypatch):
    from app.services.render_queue import _run

    _, clip = _import_video(client, tmp_path)
    monkeypatch.setattr("app.api.renders.enqueue", _run)
    config = _layout()
    config["top"].update(source_mode="solid_color", solid_color="#7834c8")
    updated = client.patch(f"/api/clips/{clip['id']}", json={"layout_type": "split_streamer_gameplay", "split_layout": config})
    assert updated.status_code == 200, updated.text
    assert updated.json()["split_layout"]["top"]["solid_color"] == "#7834c8"
    export = client.post(f"/api/clips/{clip['id']}/exports", json={"approved": True})
    assert export.status_code == 202, export.text
    job = get_render(export.json()["id"])
    assert job["status"] == "completed", job["error_message"]
    rendered = managed_path(job["output_relative_path"], must_exist=True)
    frame = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "0.2", "-i", str(rendered), "-vf", "crop=2:2:540:300", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True, timeout=30).stdout
    red, green, blue = frame[:3]
    assert abs(red - 120) < 25 and abs(green - 52) < 25 and abs(blue - 200) < 25


def test_bottom_custom_image_and_solid_color_sources_render(client, tmp_path, monkeypatch):
    from app.services.render_queue import _run

    _, clip = _import_video(client, tmp_path)
    monkeypatch.setattr("app.api.renders.enqueue", _run)
    asset = _upload_png(client, clip["id"], tmp_path).json()
    config = _layout()
    config["bottom"].update(source_mode="custom_image", image_asset_id=asset["id"], vertical_crop_percent=8)
    saved = client.patch(f"/api/clips/{clip['id']}", json={"layout_type": "split_streamer_gameplay", "split_layout": config})
    assert saved.status_code == 200, saved.text
    assert saved.json()["split_layout"]["bottom"]["source_mode"] == "custom_image"
    export = client.post(f"/api/clips/{clip['id']}/exports", json={"approved": True})
    assert export.status_code == 202, export.text
    job = get_render(export.json()["id"])
    assert job["status"] == "completed", job["error_message"]
    snapshot = json.loads(job["snapshot_json"])
    assert snapshot["layout_image_relative_paths"]["bottom"]
    rendered = managed_path(job["output_relative_path"], must_exist=True)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "json", str(rendered)], check=True, capture_output=True, text=True)
    assert any(stream.get("width") == 1080 and stream.get("height") == 1920 for stream in json.loads(probe.stdout)["streams"])

    config["bottom"].update(source_mode="solid_color", solid_color="#2860c8")
    solid = client.patch(f"/api/clips/{clip['id']}", json={"split_layout": config})
    assert solid.status_code == 200, solid.text
    assert solid.json()["split_layout"]["bottom"]["solid_color"] == "#2860c8"
    solid_export = client.post(f"/api/clips/{clip['id']}/exports", json={"approved": True})
    assert solid_export.status_code == 202, solid_export.text
    solid_job = get_render(solid_export.json()["id"])
    assert solid_job["status"] == "completed", solid_job["error_message"]

