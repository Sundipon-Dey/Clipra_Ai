from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.clip_store import claim_framing, complete_framing, create_clip, fail_framing
from app.services.framing_analysis import FramingFailure, _recommend, process_framing, validate_focal_points
from app.services.project_store import get_media_record
from app.services.storage import managed_path
from conftest import generate_video


def _import_video(client, tmp_path: Path):
    video = generate_video(tmp_path / "source.mp4", duration=1.5)
    project = client.post("/api/projects", json={"name": "Drafts"}).json()
    with video.open("rb") as stream:
        response = client.post(f"/api/projects/{project['id']}/media", files={"files": (video.name, stream, "video/mp4")})
    assert response.status_code == 200
    return response.json()["imported"][0]


def test_manual_clip_create_patch_and_duration_validation(client, tmp_path):
    media = _import_video(client, tmp_path)
    created = client.post(f"/api/media/{media['id']}/clips", json={"title": "Manual", "start_seconds": 0.2, "end_seconds": 1.0})
    assert created.status_code == 201
    clip = created.json()
    assert clip["workflow_status"] == "draft"
    assert clip["framing_mode"] == "fit"
    assert clip["focal_points"] == []
    saved = client.patch(f"/api/clips/{clip['id']}", json={"start_seconds": 0.125, "end_seconds": 1.2, "manual_focus_x": 0.72}).json()
    assert saved["manual_focus_x"] == 0.72
    reopened = client.get(f"/api/clips/{clip['id']}").json()
    assert reopened["start_seconds"] == 0.125
    assert reopened["end_seconds"] == 1.2
    assert client.patch(f"/api/clips/{clip['id']}", json={"start_seconds": 1.4}).status_code == 422
    assert client.post(f"/api/media/{media['id']}/clips", json={"title": "Invalid", "start_seconds": 0, "end_seconds": 8}).status_code == 422


def test_candidate_conversion_scoped_to_source_media(client, tmp_path):
    media = _import_video(client, tmp_path)
    from app.db.database import connect
    from app.services.project_store import create_analysis_run
    run_id = create_analysis_run(project_id=media["project_id"], media_id=media["id"], source_size_bytes=media["size_bytes"], model_name="test", prompt_version="test")
    with connect() as db:
        db.execute("UPDATE analysis_runs SET status='completed' WHERE id=?", (run_id,))
        db.execute("INSERT INTO analysis_candidates(id,analysis_id,ordinal,start_seconds,end_seconds,title,description,category,reasoning) VALUES('candidate-1',?,0,.1,.5,'A moment','Description','funny','Reason')", (run_id,))
    converted = client.post("/api/analysis-candidates/candidate-1/clips")
    assert converted.status_code == 201
    clip = converted.json()
    assert clip["source_candidate_id"] == "candidate-1"
    manual = client.post(f"/api/media/{media['id']}/clips", json={"title": "Manual", "start_seconds": 0.6, "end_seconds": 1.0}).json()
    assert manual["source_candidate_id"] is None
    assert {item["id"] for item in client.get(f"/api/media/{media['id']}/clips").json()} == {clip["id"], manual["id"]}
    assert client.get("/api/clips/not-a-clip").status_code == 404


def test_focal_point_validation_rejects_bad_timestamps_and_coordinates():
    points = validate_focal_points({"focal_points": [
        {"time_seconds": 1, "x": 0.3, "y": 0.6},
        {"time_seconds": 99, "x": 0.5, "y": 0.5},
        {"time_seconds": 1.2, "x": -1, "y": 0.5},
    ]}, start=0.5, end=1.5)
    assert len(points) == 1
    with pytest.raises(FramingFailure, match="usable focal points"):
        validate_focal_points({"focal_points": [{"time_seconds": 5, "x": 0.5, "y": 0.5}]}, start=0, end=2)


def test_framing_sdk_request_uses_only_sampled_images_and_mock_response(monkeypatch, tmp_path):
    calls = {}

    class FakeInteractions:
        def create(self, **kwargs):
            calls.update(kwargs)
            return type("Response", (), {"output_text": json.dumps({"focal_points": [{"time_seconds": 0.7, "x": .4, "y": .3}]})})()

    class FakeClient:
        def __init__(self, **kwargs): calls["client_options"] = kwargs; self.interactions = FakeInteractions()
        def close(self): pass

    monkeypatch.setattr("app.services.framing_analysis.genai.Client", FakeClient)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_model", "test-model")
    files = []
    for index in range(3):
        path = tmp_path / f"{index}.jpg"; path.write_bytes(b"tiny jpeg fixture"); files.append(path)
    clip = {"start_seconds": .5, "end_seconds": 1., "focal_points": []}
    result = _recommend(clip, files)
    assert result[0]["x"] == .4
    sent = calls["input"]
    assert sum(item.get("type") == "image" for item in sent) == 3
    assert all(item.get("type") != "video" for item in sent)
    assert calls["model"] == "test-model"
    assert calls["generation_config"]["temperature"] == 0
    assert calls["client_options"]["http_options"].retry_options.attempts == 1


def test_real_ffmpeg_frame_extraction_cleans_temp_and_preserves_source(client, tmp_path, monkeypatch):
    media_json = _import_video(client, tmp_path)
    media = get_media_record(media_json["id"])
    source = managed_path(media["source_relative_path"], must_exist=True)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    clip = create_clip(project_id=media["project_id"], media_id=media["id"], title="Frame test", start=.1, end=1.2)
    extracted = {}

    def fake_recommend(_clip, frames):
        extracted["files"] = list(frames)
        return [{"time_seconds": .5, "x": .6, "y": .4, "confidence": .8}]

    monkeypatch.setattr("app.services.framing_analysis._recommend", fake_recommend)
    process_framing(clip["id"])
    saved = client.get(f"/api/clips/{clip['id']}").json()
    assert saved["framing_status"] == "not_requested"  # no consented job was started
    # Exercise extraction/process path after the explicit queue state transition.
    from app.services.clip_store import claim_framing
    claimed, _ = claim_framing(clip["id"], retry=False)
    assert claimed
    process_framing(clip["id"])
    saved = client.get(f"/api/clips/{clip['id']}").json()
    assert saved["framing_status"] == "completed"
    assert len(extracted["files"]) == 3 and all(not path.exists() for path in extracted["files"])
    assert all(not path.parent.exists() for path in extracted["files"])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert saved["focal_points"][0]["x"] == .6


def test_framing_request_requires_consent_and_is_deduplicated(client, tmp_path, monkeypatch):
    media = _import_video(client, tmp_path)
    clip = client.post(f"/api/media/{media['id']}/clips", json={"title": "Consent", "start_seconds": .1, "end_seconds": 1.1}).json()
    monkeypatch.setattr(settings, "gemini_api_key", "configured")
    queued = []
    monkeypatch.setattr("app.api.clips.enqueue_framing", queued.append)
    assert client.post(f"/api/clips/{clip['id']}/framing-suggestion", json={"consent_to_send_frames": False}).status_code == 400
    first = client.post(f"/api/clips/{clip['id']}/framing-suggestion", json={"consent_to_send_frames": True})
    second = client.post(f"/api/clips/{clip['id']}/framing-suggestion", json={"consent_to_send_frames": True})
    assert first.status_code == 202 and first.json()["framing_status"] == "pending"
    assert second.status_code == 200 and second.json()["framing_status"] == "pending"
    assert queued == [clip["id"]]


def test_framing_restart_failure_is_recoverable(client, tmp_path):
    media_json = _import_video(client, tmp_path)
    media = get_media_record(media_json["id"])
    clip = create_clip(project_id=media["project_id"], media_id=media["id"], title="restart", start=0, end=1)
    from app.db.database import connect, initialize_database
    claimed, _ = claim_framing(clip["id"], retry=False)
    assert claimed
    initialize_database()
    # Startup recovery turns unfinished optional work into an explicit failure, never an automatic paid retry.
    with connect() as db:
        row = db.execute("SELECT framing_status,framing_error_code FROM clips WHERE id=?", (clip["id"],)).fetchone()
    assert row["framing_status"] == "failed"
    assert row["framing_error_code"] == "process_restarted"


def test_retry_preserves_previous_success_until_replacement_completes(client, tmp_path):
    media_json = _import_video(client, tmp_path)
    media = get_media_record(media_json["id"])
    clip = create_clip(project_id=media["project_id"], media_id=media["id"], title="Keep last result", start=.1, end=1.2)
    first, _ = claim_framing(clip["id"], retry=False)
    assert first
    complete_framing(clip["id"], model="test", points=[{"time_seconds": .5, "x": .4, "y": .6}])
    updated = client.patch(f"/api/clips/{clip['id']}", json={"end_seconds": 1.1}).json()
    assert updated["framing_status"] == "completed"
    assert updated["framing_end_seconds"] == 1.2
    claimed, pending = claim_framing(clip["id"], retry=True)
    assert claimed and pending["framing_status"] == "pending"
    assert pending["focal_points"][0]["x"] == .4
    fail_framing(clip["id"], code="quota_or_rate_limit", message="Quota was reached.")
    failed = client.get(f"/api/clips/{clip['id']}").json()
    assert failed["framing_status"] == "failed"
    assert failed["focal_points"][0]["x"] == .4


def test_failed_recommendation_cleans_extracted_frames_and_keeps_manual_clip(client, tmp_path, monkeypatch):
    from app.services.clip_store import claim_framing
    media_json = _import_video(client, tmp_path)
    media = get_media_record(media_json["id"])
    clip = create_clip(project_id=media["project_id"], media_id=media["id"], title="Failure stays editable", start=.1, end=1.2)
    claim_framing(clip["id"], retry=False)
    monkeypatch.setattr("app.services.framing_analysis._recommend", lambda *_: (_ for _ in ()).throw(FramingFailure("quota_or_rate_limit", "Quota was reached.")))
    process_framing(clip["id"])
    record = client.get(f"/api/clips/{clip['id']}").json()
    assert record["framing_status"] == "failed"
    assert record["framing_error_code"] == "quota_or_rate_limit"
    assert record["framing_mode"] == "fit"
    assert not list((settings.temp_dir / "framing").glob(f"{clip['id']}-*"))
