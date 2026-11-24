from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.core.config import settings
from app.db.database import connect
from app.services.project_store import utc_now
from app.services.render_store import create_export, finish, start
from app.services.storage import managed_directory, relative_path
from app.services.social_content_service import validate_packages
from app.services.social_content_service import build_context, process_generation
from app.services.social_content_store import get as get_generation
from app.services.social_content_store import create as create_generation, recovery_state, set_remote, start as start_generation, update_status
from app.services.render_store import get as get_render


def _packages():
    short = {"caption": "A caption", "opening_hook": "Wait for it", "hashtags": ["#clip"], "suggested_keywords": ["gameplay"], "alternate_caption": "Another caption"}
    return {"instagram_reels": short, "facebook_reels": short,
            "youtube_shorts": {"title": "A short", "description": "Description", "hashtags": ["#shorts"], "tags": ["gameplay"], "alternate_title": "Other title"}}


def _completed_export(client, tmp_path: Path):
    project = client.post("/api/projects", json={"name": "Social test"}).json()
    source = tmp_path / "social-source.mp4"
    from conftest import generate_video
    generate_video(source, duration=1.2)
    imported = client.post(f"/api/projects/{project['id']}/media", files={"files": ("source.mp4", source.read_bytes(), "video/mp4")}).json()["imported"][0]
    clip = client.post(f"/api/media/{imported['id']}/clips", json={"title": "A clip", "start_seconds": 0, "end_seconds": 1.0}).json()
    snapshot = {
        "clip": {"title": "A clip", "project_id": project["id"], "start_seconds": 0.0, "end_seconds": 1.0, "layout_type": "original"},
        "profile": {"resolution": "1080", "width": 1080, "height": 1920},
        "caption_track": {"segments": [{"generated_text": "The actual words."}]},
    }
    job = create_export(clip_id=clip["id"], project_id=project["id"], snapshot=snapshot, approved_at=utc_now())
    start(job["id"])
    export_dir = managed_directory(f"projects/{project['id']}/exports/{clip['id']}")
    output = export_dir / "V001-test.mp4"
    output.write_bytes(source.read_bytes())
    finish(job["id"], relative=relative_path(output), size=output.stat().st_size)
    return job["id"]


def test_validate_social_packages_requires_all_platforms_and_exact_fields():
    validated = validate_packages(_packages())
    assert set(validated) == {"instagram_reels", "youtube_shorts", "facebook_reels"}
    invalid = _packages()
    invalid["instagram_reels"]["unexpected"] = "not allowed"
    try:
        validate_packages(invalid)
        assert False, "unexpected fields should fail validation"
    except ValueError:
        pass


def test_generation_requires_per_run_consent_and_completed_export(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    render_job_id = _completed_export(client, tmp_path)
    monkeypatch.setattr("app.api.social_content.enqueue", lambda _generation_id: None)

    missing_consent = client.post(f"/api/render-jobs/{render_job_id}/social-content-generations", json={"consent_to_upload_video": False})
    assert missing_consent.status_code == 400

    with connect() as db:
        db.execute("UPDATE render_jobs SET status='processing' WHERE id=?", (render_job_id,))
    unfinished = client.post(f"/api/render-jobs/{render_job_id}/social-content-generations", json={"consent_to_upload_video": True})
    assert unfinished.status_code == 409


def test_generation_persists_output_and_user_edits_without_overwriting_original(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    render_job_id = _completed_export(client, tmp_path)
    monkeypatch.setattr("app.api.social_content.enqueue", lambda _generation_id: None)
    started = client.post(f"/api/render-jobs/{render_job_id}/social-content-generations", json={"consent_to_upload_video": True})
    assert started.status_code == 202
    generation_id = started.json()["id"]

    with connect() as db:
        db.execute("UPDATE social_content_generations SET status='completed',packages_json=?,progress=1 WHERE id=?",
                   (json.dumps(_packages()), generation_id))
    edit = _packages()["instagram_reels"] | {"caption": "My final caption"}
    saved = client.patch(f"/api/social-content-generations/{generation_id}/platforms/instagram_reels", json={"content": edit})
    assert saved.status_code == 200
    assert saved.json()["packages"]["instagram_reels"]["caption"] == "My final caption"
    assert saved.json()["generated_packages"]["instagram_reels"]["caption"] == "A caption"

    history = client.get(f"/api/render-jobs/{render_job_id}/social-content-generations")
    assert history.status_code == 200
    assert history.json()[0]["packages"]["instagram_reels"]["caption"] == "My final caption"


def test_package_edit_rejects_unknown_keys(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    render_job_id = _completed_export(client, tmp_path)
    monkeypatch.setattr("app.api.social_content.enqueue", lambda _generation_id: None)
    generation = client.post(f"/api/render-jobs/{render_job_id}/social-content-generations", json={"consent_to_upload_video": True}).json()
    invalid = _packages()["instagram_reels"] | {"unexpected": "value"}
    result = client.patch(f"/api/social-content-generations/{generation['id']}/platforms/instagram_reels", json={"content": invalid})
    assert result.status_code == 422


def test_worker_uploads_exact_export_and_cleans_gemini_files(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    render_job_id = _completed_export(client, tmp_path)
    uploaded = []
    deleted_files = []
    generation_calls = []
    output_text = json.dumps(_packages())
    remote_file = SimpleNamespace(name="files/temp-social", uri="https://files.invalid/temp-social", state=SimpleNamespace(name="ACTIVE"))
    client_mock = SimpleNamespace(
        files=SimpleNamespace(
            upload=lambda *, file, config: (uploaded.append((file, config)) or remote_file),
            get=lambda **_kwargs: remote_file,
            delete=lambda *, name: deleted_files.append(name),
        ),
        models=SimpleNamespace(generate_content=lambda **kwargs: (generation_calls.append(kwargs) or SimpleNamespace(text=output_text))),
        close=lambda: None,
    )
    monkeypatch.setattr("app.services.social_content_service.genai.Client", lambda **_kwargs: client_mock)
    monkeypatch.setattr("app.api.social_content.enqueue", lambda _generation_id: None)
    response = client.post(f"/api/render-jobs/{render_job_id}/social-content-generations", json={"consent_to_upload_video": True})
    generation_id = response.json()["id"]

    process_generation(generation_id)
    record = get_generation(generation_id)
    assert record["status"] == "completed"
    assert record["generated_packages"]["youtube_shorts"]["title"] == "A short"
    assert uploaded[0][0].name.startswith("V001-")
    assert uploaded[0][1]["mime_type"] == "video/mp4"
    assert generation_calls[0]["contents"][0] is remote_file
    assert "Clip/export context JSON" in generation_calls[0]["contents"][1]
    assert generation_calls[0]["config"].response_mime_type == "application/json"
    assert deleted_files == ["files/temp-social"]
    assert record["cleanup_pending"] is False


def test_context_uses_clipwing_entry_tied_to_exported_clip(client, tmp_path):
    render_job_id = _completed_export(client, tmp_path)
    job = get_render(render_job_id)
    with connect() as db:
        project_id = db.execute("SELECT project_id FROM render_jobs WHERE id=?", (render_job_id,)).fetchone()[0]
        media_id = db.execute("SELECT media_id FROM clips WHERE id=?", (job["clip_id"],)).fetchone()[0]
        now = utc_now()
        db.execute("INSERT INTO clipwing_imports(id,project_id,video_url,analysis_text,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                   ("import-social", project_id, "https://youtu.be/abcdefghijk", "pasted analysis", "completed", now, now))
        db.execute("INSERT INTO clipwing_entries(id,import_id,ordinal,title,start_seconds,end_seconds,score,transcript,video_url,status,progress,media_id,clip_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("entry-social", "import-social", 0, "Moment title", 4, 9, 91, "Provided quote", "https://youtu.be/abcdefghijk", "ready", 1, media_id, job["clip_id"]))
    context = build_context(job)
    assert context["source_type"] == "clipwing"
    assert context["clipwing_moment"]["title"] == "Moment title"
    assert context["clipwing_moment"]["transcript_excerpt"] == "Provided quote"
    assert context["clipwing_moment"]["video_url"] == "https://youtu.be/abcdefghijk"
    assert context["caption_transcript"] == "The actual words."


def test_restart_marks_billable_work_interrupted_and_does_not_queue_retry(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    render_job_id = _completed_export(client, tmp_path)
    generation_id = create_generation(render_job_id=render_job_id, model_name="configured-model", prompt_version="stage6-social-v1", consent_at=utc_now(), context={})
    assert start_generation(generation_id)
    update_status(generation_id, "processing_file", "preparing_video", .25)
    set_remote(generation_id, file_name="files/interrupted")
    queued, cleanup = recovery_state()
    assert generation_id not in queued
    assert generation_id in cleanup
    record = get_generation(generation_id)
    assert record["status"] == "interrupted"
    assert record["error_code"] == "process_restarted"


def test_failed_generation_can_copy_exact_prompt_and_import_manual_packages(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    render_job_id = _completed_export(client, tmp_path)
    monkeypatch.setattr("app.api.social_content.enqueue", lambda _generation_id: None)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    generation = client.post(f"/api/render-jobs/{render_job_id}/social-content-generations", json={"consent_to_upload_video": True}).json()
    generation_id = generation["id"]
    with connect() as db:
        db.execute("UPDATE social_content_generations SET status='failed',stage='failed',error_message='Gemini unavailable',cleanup_pending=1 WHERE id=?", (generation_id,))

    prompt = client.get(f"/api/social-content-generations/{generation_id}/manual-prompt")
    assert prompt.status_code == 200
    assert "instagram_reels, youtube_shorts, facebook_reels" in prompt.json()["prompt"]
    assert "opening_hook" in prompt.json()["prompt"] and "alternate_title" in prompt.json()["prompt"]
    assert "The actual words." in prompt.json()["prompt"]
    assert "Return ONLY one valid JSON object" in prompt.json()["prompt"]

    invalid = client.post(f"/api/social-content-generations/{generation_id}/manual-import", json={"output": "not json"})
    assert invalid.status_code == 422
    assert client.get(f"/api/social-content-generations/{generation_id}").json()["status"] == "failed"

    imported = client.post(f"/api/social-content-generations/{generation_id}/manual-import", json={"output": json.dumps(_packages())})
    assert imported.status_code == 200
    body = imported.json()
    assert body["status"] == "completed"
    assert body["model_name"] == "manual-fallback"
    assert body["packages"]["instagram_reels"]["caption"] == "A caption"
    assert body["packages"]["youtube_shorts"]["title"] == "A short"
    assert body["cleanup_pending"] is True
    assert body["error_message"] is None

    duplicate = client.post(f"/api/social-content-generations/{generation_id}/manual-import", json={"output": json.dumps(_packages())})
    assert duplicate.status_code == 409
