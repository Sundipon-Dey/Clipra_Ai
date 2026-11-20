from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from app.core.config import settings
from app.db.database import connect, initialize_database
from app.services import highlight_analysis
from app.services.highlight_analysis import validate_and_deduplicate_candidates
from app.services.project_store import create_analysis_run, get_analysis_run_record
from app.services.storage import managed_path
from conftest import generate_video


def _candidate(start: float, end: float, *, confidence: float = 0.8, title: str = "Moment"):
    return {
        "start_seconds": start,
        "end_seconds": end,
        "title": title,
        "description": "A synthetic test highlight.",
        "category": "exciting",
        "reasoning": "The visible action has a clear payoff.",
        "confidence": confidence,
    }


def _import_video(client, path: Path) -> dict:
    project = client.post("/api/projects", json={"name": "Analysis test"}).json()
    response = client.post(
        f"/api/projects/{project['id']}/media",
        files=[("files", (path.name, path.read_bytes(), "video/mp4"))],
    )
    assert response.status_code == 200, response.text
    return response.json()["imported"][0]


def test_candidate_validation_rejects_invalid_timestamps_and_collapses_overlap():
    result = validate_and_deduplicate_candidates(
        {"candidates": [
            _candidate(-0.1, 1.0),
            _candidate(1.0, 0.9),
            _candidate(8.0, 11.0),
            _candidate(1.0, 4.0, confidence=0.91, title="Best moment"),
            _candidate(1.2, 3.8, confidence=0.7, title="Duplicate moment"),
            _candidate(5.0, 7.0, confidence=0.6, title="Separate moment"),
        ]},
        duration_seconds=10.0,
    )
    assert [item["title"] for item in result] == ["Best moment", "Separate moment"]


def test_malformed_response_is_rejected():
    try:
        validate_and_deduplicate_candidates({"items": []}, 10)
    except highlight_analysis.AnalysisFailure as error:
        assert error.code == "malformed_response"
    else:
        raise AssertionError("Malformed response was accepted")


def test_process_analysis_uses_managed_copy_and_cleans_up_remote_file(client, workspace, tmp_path, monkeypatch):
    settings.gemini_api_key = "mock-only-secret"
    settings.gemini_model = "gemini-3.5-flash-lite"
    original = generate_video(tmp_path / "local-original.mp4", duration=2.0)
    before_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    media = _import_video(client, original)
    run_id = create_analysis_run(
        project_id=media["project_id"], media_id=media["id"],
        source_size_bytes=media["size_bytes"], model_name=settings.gemini_model,
        prompt_version=highlight_analysis.PROMPT_VERSION,
    )
    response_json = json.dumps({"candidates": [_candidate(0.25, 1.25)]})
    calls: dict[str, object] = {}

    class FakeFiles:
        def upload(self, *, file, config):
            calls["upload_file"] = Path(file)
            calls["upload_config"] = config
            return SimpleNamespace(name="files/mock-id", uri="https://files.invalid/mock-id", state=SimpleNamespace(name="ACTIVE"))

        def delete(self, *, name):
            calls["deleted"] = name

    class FakeInteractions:
        def create(self, **kwargs):
            calls["interaction"] = kwargs
            return SimpleNamespace(id="interaction/mock-id", status="in_progress")

        def get(self, *, id):
            calls["polled_interaction"] = id
            return SimpleNamespace(id=id, status="completed", output_text=response_json)

        def delete(self, *, id):
            calls["deleted_interaction"] = id

    class FakeClient:
        def __init__(self, **kwargs):
            calls["client_config"] = kwargs
            self.files = FakeFiles()
            self.interactions = FakeInteractions()

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(highlight_analysis.genai, "Client", FakeClient)
    highlight_analysis.process_analysis(run_id)

    run = get_analysis_run_record(run_id)
    assert run["status"] == "completed"
    assert run["cleanup_pending"] == 0
    assert run["remote_file_name"] == ""
    assert calls["deleted"] == "files/mock-id"
    assert calls["upload_file"] != original
    assert calls["upload_file"].is_relative_to(workspace)
    assert calls["upload_config"]["mime_type"] == "video/mp4"
    client_config = calls["client_config"]
    assert client_config["http_options"].retry_options.attempts == 1
    assert client_config["http_options"].api_version == "v1beta"
    interaction = calls["interaction"]
    assert interaction["model"] == "gemini-3.5-flash-lite"
    assert interaction["input"][0]["processing"] == "agentic"
    assert interaction["response_format"]["mime_type"] == "application/json"
    assert "store" not in interaction
    assert interaction["background"] is True
    assert calls["polled_interaction"] == "interaction/mock-id"
    assert calls["deleted_interaction"] == "interaction/mock-id"
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before_hash
    history = client.get(f"/api/media/{media['id']}/analyses")
    # The synchronous fake runner is invoked directly; history is still persisted and queryable.
    assert history.status_code == 200
    assert history.json()[0]["candidates"][0]["title"] == "Moment"


def test_missing_source_fails_before_any_gemini_client_creation(client, workspace, tmp_path, monkeypatch):
    original = generate_video(tmp_path / "missing-source.mp4", duration=1.5)
    media = _import_video(client, original)
    run_id = create_analysis_run(
        project_id=media["project_id"], media_id=media["id"], source_size_bytes=media["size_bytes"],
        model_name="gemini-3.5-flash-lite", prompt_version=highlight_analysis.PROMPT_VERSION,
    )
    with connect() as connection:
        relative = connection.execute("SELECT source_relative_path FROM media WHERE id=?", (media["id"],)).fetchone()[0]
    managed_path(relative).unlink()
    monkeypatch.setattr(highlight_analysis.genai, "Client", lambda **_: (_ for _ in ()).throw(AssertionError("Gemini must not be called")))

    highlight_analysis.process_analysis(run_id)

    run = get_analysis_run_record(run_id)
    assert run["status"] == "failed"
    assert run["error_code"] == "source_missing"


def test_gemini_unsupported_mkv_fails_before_remote_upload(client, tmp_path, monkeypatch):
    settings.gemini_api_key = "mock-only-secret"
    original = generate_video(tmp_path / "unsupported.mkv", duration=1.5)
    media = _import_video(client, original)
    run_id = create_analysis_run(
        project_id=media["project_id"], media_id=media["id"], source_size_bytes=media["size_bytes"],
        model_name="gemini-3.5-flash-lite", prompt_version=highlight_analysis.PROMPT_VERSION,
    )
    def unexpected_client(**kwargs):
        raise AssertionError("unsupported video must not upload")
    monkeypatch.setattr(highlight_analysis.genai, "Client", unexpected_client)
    highlight_analysis.process_analysis(run_id)
    run = get_analysis_run_record(run_id)
    assert run["status"] == "failed"
    assert run["error_code"] == "unsupported_media"


def test_gemini_failure_is_recorded_without_automatic_retry(client, tmp_path, monkeypatch):
    settings.gemini_api_key = "mock-only-secret"
    original = generate_video(tmp_path / "api-failure.mp4", duration=1.5)
    media = _import_video(client, original)
    run_id = create_analysis_run(
        project_id=media["project_id"], media_id=media["id"], source_size_bytes=media["size_bytes"],
        model_name="gemini-3.5-flash-lite", prompt_version=highlight_analysis.PROMPT_VERSION,
    )
    calls = {"upload": 0, "interactions": 0}

    class FakeFiles:
        def upload(self, **kwargs):
            calls["upload"] += 1
            return SimpleNamespace(name="files/mock-id", uri="https://files.invalid/mock-id", state=SimpleNamespace(name="ACTIVE"))

        def delete(self, **kwargs):
            pass

    class FakeInteractions:
        def create(self, **kwargs):
            calls["interactions"] += 1
            raise RuntimeError("private SDK details must not reach the user")

    class FakeClient:
        def __init__(self, **kwargs):
            self.files, self.interactions = FakeFiles(), FakeInteractions()
        def close(self):
            pass

    monkeypatch.setattr(highlight_analysis.genai, "Client", FakeClient)
    highlight_analysis.process_analysis(run_id)
    run = get_analysis_run_record(run_id)
    assert run["status"] == "failed"
    assert "private SDK details" not in run["error_message"]
    assert calls == {"upload": 1, "interactions": 1}


def test_remote_cleanup_failure_is_persisted_for_user_visibility(client, tmp_path, monkeypatch):
    settings.gemini_api_key = "mock-only-secret"
    original = generate_video(tmp_path / "cleanup-failure.mp4", duration=1.5)
    media = _import_video(client, original)
    run_id = create_analysis_run(
        project_id=media["project_id"], media_id=media["id"], source_size_bytes=media["size_bytes"],
        model_name="gemini-3.5-flash-lite", prompt_version=highlight_analysis.PROMPT_VERSION,
    )

    class FakeFiles:
        def upload(self, **kwargs):
            return SimpleNamespace(name="files/orphan", uri="https://files.invalid/orphan", state=SimpleNamespace(name="ACTIVE"))
        def delete(self, **kwargs):
            raise RuntimeError("remote cleanup transport detail")

    class FakeClient:
        def __init__(self, **kwargs):
            self.files = FakeFiles()
            self.interactions = SimpleNamespace(create=lambda **_: SimpleNamespace(id="interaction/cleanup-test", status="completed", output_text='{"candidates": []}'))
        def close(self):
            pass

    monkeypatch.setattr(highlight_analysis.genai, "Client", FakeClient)
    highlight_analysis.process_analysis(run_id)
    run = get_analysis_run_record(run_id)
    assert run["status"] == "completed"
    assert run["cleanup_pending"] == 1
    assert run["remote_file_name"] == "files/orphan"
    assert "transport detail" not in (run["error_message"] or "")


def test_interrupted_remote_analysis_is_cancelled_and_file_deleted(client, tmp_path, monkeypatch):
    settings.gemini_api_key = "mock-only-secret"
    original = generate_video(tmp_path / "interrupted-remote.mp4", duration=1.5)
    media = _import_video(client, original)
    run_id = create_analysis_run(
        project_id=media["project_id"], media_id=media["id"], source_size_bytes=media["size_bytes"],
        model_name="gemini-3.5-flash-lite", prompt_version=highlight_analysis.PROMPT_VERSION,
    )
    with connect() as connection:
        connection.execute(
            "UPDATE analysis_runs SET status='interrupted', remote_file_name=?, remote_interaction_id=?, cleanup_pending=1 WHERE id=?",
            ("files/stale", "interaction/stale", run_id),
        )
    calls: list[str] = []

    class FakeFiles:
        def delete(self, *, name):
            calls.append("file:" + name)

    class FakeInteractions:
        def get(self, *, id):
            calls.append("get:" + id)
            return SimpleNamespace(status="in_progress")
        def cancel(self, *, id):
            calls.append("cancel:" + id)
            return SimpleNamespace(status="cancelled")
        def delete(self, *, id):
            calls.append("delete-interaction:" + id)

    class FakeClient:
        def __init__(self, **kwargs):
            self.files, self.interactions = FakeFiles(), FakeInteractions()
        def close(self):
            pass

    monkeypatch.setattr(highlight_analysis.genai, "Client", FakeClient)
    highlight_analysis.cleanup_interrupted_analysis(run_id)
    run = get_analysis_run_record(run_id)
    assert calls == ["get:interaction/stale", "cancel:interaction/stale", "delete-interaction:interaction/stale", "file:files/stale"]
    assert run["status"] == "interrupted"
    assert run["cleanup_pending"] == 0
    assert run["remote_file_name"] == ""
    assert run["remote_interaction_id"] == ""


def test_background_interaction_timeout_is_cancelled_without_retry(client, tmp_path, monkeypatch):
    settings.gemini_api_key = "mock-only-secret"
    settings.gemini_interaction_timeout_seconds = 60
    original = generate_video(tmp_path / "timeout.mp4", duration=1.5)
    media = _import_video(client, original)
    run_id = create_analysis_run(
        project_id=media["project_id"], media_id=media["id"], source_size_bytes=media["size_bytes"],
        model_name="gemini-3.5-flash-lite", prompt_version=highlight_analysis.PROMPT_VERSION,
    )
    calls = {"create": 0, "cancel": 0, "poll": 0}

    class FakeFiles:
        def upload(self, **kwargs):
            return SimpleNamespace(name="files/timeout", uri="https://files.invalid/timeout", state=SimpleNamespace(name="ACTIVE"))
        def delete(self, **kwargs):
            pass

    class FakeInteractions:
        def create(self, **kwargs):
            calls["create"] += 1
            return SimpleNamespace(id="interaction/timeout", status="in_progress")
        def get(self, **kwargs):
            calls["poll"] += 1
            return SimpleNamespace(id="interaction/timeout", status="in_progress")
        def cancel(self, **kwargs):
            calls["cancel"] += 1
            return SimpleNamespace(status="cancelled")
        def delete(self, **kwargs):
            calls["delete"] = 1

    class FakeClient:
        def __init__(self, **kwargs):
            self.files, self.interactions = FakeFiles(), FakeInteractions()
        def close(self):
            pass

    ticks = iter([0.0, 0.0, 61.0])
    fake_clock = SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _: None)
    monkeypatch.setattr(highlight_analysis.genai, "Client", FakeClient)
    monkeypatch.setattr(highlight_analysis, "time", fake_clock)
    highlight_analysis.process_analysis(run_id)
    run = get_analysis_run_record(run_id)
    assert run["status"] == "failed"
    assert run["error_code"] == "analysis_timeout"
    assert calls == {"create": 1, "cancel": 1, "poll": 0, "delete": 1}


def test_quota_errors_are_sanitized_and_not_retried():
    from google.genai import errors

    error = errors.APIError(429, {"error": {"message": "quota details with sensitive metadata"}})
    code, message = highlight_analysis._error_details(error)
    assert code == "quota_or_rate_limit"
    assert "quota" in message.lower()
    assert "sensitive metadata" not in message


def test_restart_marks_in_flight_jobs_interrupted_but_recovers_queued(client, workspace, tmp_path, monkeypatch):
    original = generate_video(tmp_path / "restart-queued.mp4", duration=1.5)
    media = _import_video(client, original)
    original_inflight = generate_video(tmp_path / "restart-inflight.mp4", duration=1.5)
    media_inflight = _import_video(client, original_inflight)
    queued_id = create_analysis_run(
        project_id=media["project_id"], media_id=media["id"], source_size_bytes=media["size_bytes"],
        model_name="gemini-3.5-flash-lite", prompt_version=highlight_analysis.PROMPT_VERSION,
    )
    interrupted_id = create_analysis_run(
        project_id=media_inflight["project_id"], media_id=media_inflight["id"], source_size_bytes=media_inflight["size_bytes"],
        model_name="gemini-3.5-flash-lite", prompt_version=highlight_analysis.PROMPT_VERSION,
    )
    with connect() as connection:
        connection.execute("UPDATE analysis_runs SET status='analyzing' WHERE id=?", (interrupted_id,))
    initialize_database()
    assert get_analysis_run_record(queued_id)["status"] == "queued"
    interrupted = get_analysis_run_record(interrupted_id)
    assert interrupted["status"] == "interrupted"
    assert interrupted["error_code"] == "process_restarted"
    recovered: list[str] = []
    monkeypatch.setattr("app.services.analysis_queue.enqueue_analysis", recovered.append)
    from app.services.analysis_queue import recover_queued_analyses
    recover_queued_analyses()
    assert recovered == [queued_id]


def test_analysis_api_is_idempotent_until_explicit_rerun(client, tmp_path, monkeypatch):
    settings.gemini_api_key = "mock-only-secret"
    original = generate_video(tmp_path / "api-runs.mp4", duration=1.5)
    media = _import_video(client, original)
    scheduled: list[str] = []
    monkeypatch.setattr("app.api.analyses.enqueue_analysis", scheduled.append)

    first = client.post(f"/api/media/{media['id']}/analyses", json={"force": False})
    assert first.status_code == 202
    first_run = first.json()
    assert first_run["status"] == "queued"
    assert first_run["model_name"] == "gemini-3.5-flash-lite"
    assert "mock-only-secret" not in first.text

    repeated = client.post(f"/api/media/{media['id']}/analyses", json={"force": False})
    assert repeated.status_code == 200
    assert repeated.json()["id"] == first_run["id"]
    assert scheduled == [first_run["id"]]

    with connect() as connection:
        connection.execute("UPDATE analysis_runs SET status='completed' WHERE id=?", (first_run["id"],))
    rerun = client.post(f"/api/media/{media['id']}/analyses", json={"force": True})
    assert rerun.status_code == 202
    assert rerun.json()["id"] != first_run["id"]
    assert scheduled == [first_run["id"], rerun.json()["id"]]

    history = client.get(f"/api/media/{media['id']}/analyses")
    detail = client.get(f"/api/analyses/{first_run['id']}")
    assert history.status_code == detail.status_code == 200
    assert len(history.json()) == 2
    assert detail.json()["id"] == first_run["id"]


def test_analysis_endpoint_requires_backend_key(client, tmp_path, monkeypatch):
    original = generate_video(tmp_path / "no-key.mp4", duration=1.5)
    media = _import_video(client, original)
    monkeypatch.setattr(settings, "gemini_api_key", "")
    response = client.post(f"/api/media/{media['id']}/analyses", json={"force": False})
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]
