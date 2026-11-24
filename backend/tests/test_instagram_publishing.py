from __future__ import annotations

import json
import logging
import urllib.error
from pathlib import Path

import pytest

from app.services import facebook_auth, instagram_auth, instagram_r2_storage as r2, instagram_upload_service as service
from app.services.instagram_r2_storage import R2StorageError
from conftest import generate_video


def test_meta_oauth_requests_only_platform_scopes_needed():
    facebook_scopes = facebook_auth.authorization_permissions()
    instagram_scopes = facebook_auth.authorization_permissions(include_instagram=True)
    assert facebook_scopes == ("pages_show_list", "pages_read_engagement", "pages_manage_posts", "business_management")
    assert "instagram_basic" not in facebook_scopes
    assert "instagram_content_publish" not in facebook_scopes
    assert set(instagram_scopes) == set(facebook_scopes) | {"instagram_basic", "instagram_content_publish"}


def test_business_owned_page_discovery_uses_business_management_edges(monkeypatch):
    requested_urls = []

    def fake_request(url):
        requested_urls.append(url)
        if "/me/businesses?" in url:
            return {"data": [{"id": "business1", "name": "VYRUSH"}]}
        if "/business1/owned_pages?" in url:
            return {"data": [{"id": "page1", "name": "Vyrush HQ", "access_token": "page-token", "tasks": ["CREATE_CONTENT"]}]}
        raise AssertionError(f"Unexpected Graph API URL: {url}")

    monkeypatch.setattr(facebook_auth, "_json_request", fake_request)
    assert facebook_auth._business_owned_pages("user-token") == [
        {"id": "page1", "name": "Vyrush HQ", "access_token": "page-token", "tasks": ["CREATE_CONTENT"]},
    ]
    assert len(requested_urls) == 2


def test_meta_permission_diagnostic_returns_only_permission_status(monkeypatch):
    monkeypatch.setattr(facebook_auth, "_json_request", lambda _url: {"data": [
        {"permission": "pages_show_list", "status": "granted"},
        {"permission": "pages_manage_posts", "status": "declined"},
        {"permission": "email", "status": "granted"},
    ]})
    assert facebook_auth._granted_permission_statuses("private-token") == {
        "pages_show_list": "granted", "pages_manage_posts": "declined", "email": "granted",
    }


def test_instagram_discovery_exposes_only_linked_professional_accounts(monkeypatch):
    monkeypatch.setattr(instagram_auth.facebook_auth, "pages", lambda: [
        {"id": "page1", "name": "Creator Page", "instagram_user_id": "ig1", "instagram_username": "creator"},
        {"id": "page2", "name": "Unlinked Page", "access_token": "private-token"},
    ])
    assert instagram_auth.accounts() == [{
        "instagram_user_id": "ig1", "instagram_username": "creator", "page_id": "page1", "page_name": "Creator Page",
    }]
    assert instagram_auth.selected_account("missing") is None


def test_caption_uses_saved_caption_and_normalizes_hashtags():
    assert service._caption({"caption": "A Reel", "hashtags": ["games", "#clips"]}) == "A Reel\n\n#games #clips"
    assert service._caption({"opening_hook": "Hook", "hashtags": []}) == "Hook"


def test_caption_rejects_instagram_limit_overflow():
    with pytest.raises(service.InstagramUploadError, match="2,200"):
        service._caption({"caption": "x" * 2201})


def test_reel_preflight_accepts_synthetic_mp4(tmp_path: Path):
    service._validate_reel_file(generate_video(tmp_path / "instagram.mp4", duration=3.4))


def test_r2_key_and_presign_configuration(monkeypatch, tmp_path: Path):
    from app.services import instagram_r2_storage

    calls = {}

    class FakeS3:
        def upload_file(self, filename, bucket, key, **kwargs):
            calls.update(filename=filename, bucket=bucket, key=key, **kwargs)

        def generate_presigned_url(self, operation, *, Params, ExpiresIn):
            calls.setdefault("presigns", []).append((operation, Params, ExpiresIn))
            return f"https://test.r2.cloudflarestorage.com/clipra-ai/ig-reels/test.mp4?method={operation}&X-Amz-Signature=SECRET"

    class FakeBoto:
        @staticmethod
        def client(*args, **kwargs):
            calls["client_args"] = args
            calls["client_kwargs"] = kwargs
            return FakeS3()

    class FakeTransferConfig:
        def __init__(self, **kwargs):
            calls["transfer_config"] = kwargs

    import boto3.s3.transfer
    monkeypatch.setattr(instagram_r2_storage.settings, "r2_account_id", "account")
    monkeypatch.setattr(instagram_r2_storage.settings, "r2_bucket", "clipra-ai")
    monkeypatch.setattr(instagram_r2_storage.settings, "r2_access_key_id", "key")
    monkeypatch.setattr(instagram_r2_storage.settings, "r2_secret_access_key", "secret")
    monkeypatch.setattr("boto3.client", FakeBoto.client)
    monkeypatch.setattr(boto3.s3.transfer, "TransferConfig", FakeTransferConfig)
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"synthetic-mp4")
    key = instagram_r2_storage.new_object_key()
    url = instagram_r2_storage.upload_object(path, key)

    assert key.startswith("ig-reels/") and key.endswith(".mp4")
    assert calls["bucket"] == "clipra-ai"
    assert calls["ExtraArgs"] == {"ContentType": "video/mp4"}
    assert calls["client_kwargs"]["endpoint_url"] == "https://account.r2.cloudflarestorage.com"
    assert calls["client_kwargs"]["region_name"] == "auto"
    assert {item[0] for item in calls["presigns"]} == {"get_object", "head_object"}
    assert all(item[2] == 7200 for item in calls["presigns"])
    assert "X-Amz-Signature=SECRET" in url.get_url
    assert "method=head_object" in url.head_url


def test_r2_head_rejects_redirect_and_wrong_metadata(monkeypatch):
    class FakeResponse:
        status = 200

        def __init__(self, headers):
            self.headers = headers

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeOpener:
        def __init__(self, response=None, error=None):
            self.response, self.error = response, error

        def open(self, _request, timeout):
            if self.error:
                raise self.error
            return self.response

    monkeypatch.setattr(r2.urllib.request, "build_opener", lambda *_args: FakeOpener(FakeResponse({"Content-Type": "video/mp4", "Content-Length": "5"})))
    r2.verify_presigned_url("https://r2.test/object", 5)
    with pytest.raises(R2StorageError, match="Content-Length"):
        monkeypatch.setattr(r2.urllib.request, "build_opener", lambda *_args: FakeOpener(FakeResponse({"Content-Type": "video/mp4", "Content-Length": "4"})))
        r2.verify_presigned_url("https://r2.test/object", 5)
    redirect = urllib.error.HTTPError("https://r2.test/object", 302, "Found", {}, None)
    monkeypatch.setattr(r2.urllib.request, "build_opener", lambda *_args: FakeOpener(error=redirect))
    with pytest.raises(R2StorageError, match="redirect"):
        r2.verify_presigned_url("https://r2.test/object", 5)


def test_meta_response_logs_body_trace_and_redacts_secrets(caplog, monkeypatch):
    error_body = json.dumps({"error": {"message": "bad input", "video_url": "https://r2.test/reel.mp4?X-Amz-Signature=SECRET", "access_token": "EAAabcdefghijklmnopqrstuvwxyz12345678901234567890"}}).encode()
    response = urllib.error.HTTPError("https://graph.test", 400, "Bad Request", {"x-fb-trace-id": "trace-123"}, None)
    response.read = lambda _size=-1: error_body
    monkeypatch.setattr(service.urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(response))
    caplog.set_level(logging.INFO, logger=service.__name__)
    request = service.urllib.request.Request("https://graph.test")
    with pytest.raises(service.InstagramMetaError) as caught:
        service._send_graph(request, "POST /v25.0/ig1/media")
    assert "bad input" in str(caught.value)
    assert "trace-123" in str(caught.value)
    assert "SECRET" not in caplog.text and "EAAabcdefghijklmnopqrstuvwxyz" not in caplog.text
    assert "trace-123" in caplog.text and "status=400" in caplog.text


def _stub_run(monkeypatch, tmp_path, *, status="FINISHED", publish_error=False, delete_error=False):
    calls = []
    state = {"failed": [], "finished": [], "deleted": []}
    video = tmp_path / "export.mp4"
    video.write_bytes(b"media")
    account = {"instagram_user_id": "ig1", "page_id": "page1", "page_name": "Page", "instagram_username": "creator"}
    page = {"instagram_user_id": "ig1", "access_token": "private-token"}
    monkeypatch.setattr(service.store, "start", lambda _id: True)
    monkeypatch.setattr(service.store, "set_r2_object", lambda _id, key: calls.append(("object", key)))
    monkeypatch.setattr(service.store, "set_container", lambda _id, cid: calls.append(("container", cid)))
    monkeypatch.setattr(service.store, "progress", lambda *_args: None)
    monkeypatch.setattr(service.store, "finish", lambda *args: state["finished"].append(args))
    monkeypatch.setattr(service.store, "fail", lambda *args: state["failed"].append(args))
    monkeypatch.setattr(service.instagram_auth, "selected_account", lambda _id: account)
    monkeypatch.setattr(service.facebook_auth, "selected_page", lambda _id: page)
    monkeypatch.setattr(service, "_validate_reel_file", lambda _path: {"format": {"duration": "5"}})
    monkeypatch.setattr(service.instagram_r2_storage, "new_object_key", lambda: "ig-reels/test.mp4")
    monkeypatch.setattr(service.instagram_r2_storage, "upload_object", lambda *_args, **kwargs: (calls.append(("r2_upload", kwargs)) or r2.PresignedObjectUrls("https://r2.test/file?X-Amz-Signature=SECRET", "https://r2.test/file?head-signature=SECRET")))
    monkeypatch.setattr(service.instagram_r2_storage, "verify_presigned_url", lambda *_args: calls.append(("head",)))

    def delete(key):
        calls.append(("delete", key))
        state["deleted"].append(key)
        if delete_error:
            raise R2StorageError("cleanup issue")

    monkeypatch.setattr(service.instagram_r2_storage, "delete_object", delete)

    def post(path, fields):
        calls.append(("post", path, fields))
        if path.endswith("/media"):
            return {"id": "987654"}
        if publish_error:
            raise service.InstagramMetaError('HTTP 400. Response body: {"error":{"message":"publish failed"}}', http_status=400)
        return {"id": "123456"}

    monkeypatch.setattr(service, "_graph_request", post)
    monkeypatch.setattr(service, "_wait_until_ready", lambda *_args: (calls.append(("poll",)), (_ for _ in ()).throw(service.InstagramContainerTerminalError(f"Instagram container reached {status}. Meta status: {{\"status_code\":\"{status}\",\"status\":\"failed details\"}}")) if status in {"ERROR", "EXPIRED"} else None)[1])
    monkeypatch.setattr(service, "_graph_get", lambda *_args: (calls.append(("permalink",)) or {"permalink": "https://instagram.test/reel/1"}))
    return video, calls, state


def test_video_url_publish_waits_for_finished_then_deletes(monkeypatch, tmp_path: Path):
    video, calls, state = _stub_run(monkeypatch, tmp_path)
    service.run("upload1", video, {"caption": "Reviewed", "hashtags": ["clip"]}, "ig1")
    create = next(call[2] for call in calls if call[0] == "post" and call[1] == "ig1/media")
    assert create["media_type"] == "REELS"
    assert create["video_url"].startswith("https://r2.test/")
    assert "upload_type" not in create
    assert all(call[0] != "transfer" for call in calls)
    assert calls.index(next(call for call in calls if call[0] == "poll")) < calls.index(next(call for call in calls if call[0] == "post" and call[1].endswith("/media_publish")))
    assert calls[-1] == ("delete", "ig-reels/test.mp4")
    assert state["finished"] == [("upload1", "123456", "https://instagram.test/reel/1")]
    assert not state["failed"]


def test_container_error_surfaces_details_and_deletes_terminal_object(monkeypatch, tmp_path: Path):
    video, calls, state = _stub_run(monkeypatch, tmp_path, status="ERROR")
    service.run("upload1", video, {"caption": "Reviewed"}, "ig1")
    assert "failed details" in state["failed"][0][1]
    assert not any(call[0] == "post" and call[1].endswith("/media_publish") for call in calls)
    assert state["deleted"] == ["ig-reels/test.mp4"]


def test_timeout_retains_object_while_container_may_be_processing(monkeypatch, tmp_path: Path):
    video, calls, state = _stub_run(monkeypatch, tmp_path)
    monkeypatch.setattr(service, "_wait_until_ready", lambda *_args: (_ for _ in ()).throw(service.InstagramProcessingTimeout("timed out; retained")))
    service.run("upload1", video, {"caption": "Reviewed"}, "ig1")
    assert "timed out" in state["failed"][0][1]
    assert not state["deleted"]
    assert not any(call[0] == "post" and call[1].endswith("/media_publish") for call in calls)


def test_cleanup_failure_does_not_fail_successful_publish(monkeypatch, tmp_path: Path, caplog):
    video, _calls, state = _stub_run(monkeypatch, tmp_path, delete_error=True)
    caplog.set_level(logging.WARNING, logger=service.__name__)
    service.run("upload1", video, {"caption": "Reviewed"}, "ig1")
    assert state["finished"]
    assert not state["failed"]
    assert "cleanup failed" in caplog.text


def test_publish_meta_error_is_saved_and_r2_deleted_after_finished(monkeypatch, tmp_path: Path):
    video, calls, state = _stub_run(monkeypatch, tmp_path, publish_error=True)
    service.run("upload1", video, {"caption": "Reviewed"}, "ig1")
    assert "publish failed" in state["failed"][0][1]
    assert state["deleted"] == ["ig-reels/test.mp4"]


def test_instagram_publish_api_requires_explicit_approval(client):
    rejected = client.post("/api/social/instagram/exports/missing/uploads", json={
        "generation_id": "generation", "instagram_user_id": "instagram",
    })
    assert rejected.status_code == 400
    assert "Explicitly approve" in rejected.json()["detail"]


def test_instagram_upload_api_requires_r2_configuration(client, monkeypatch):
    from app.api import instagram as api

    monkeypatch.setattr(api.instagram_r2_storage, "configured", lambda: False)
    response = client.post("/api/social/instagram/exports/missing/uploads", json={
        "approved": True, "generation_id": "generation", "instagram_user_id": "instagram",
    })
    assert response.status_code == 409
    assert "Cloudflare R2" in response.json()["detail"]


def test_instagram_upload_api_queues_without_legacy_variant(client, tmp_path: Path, monkeypatch):
    from app.api import instagram as api

    account = {"instagram_user_id": "ig123", "page_id": "page123", "page_name": "Page", "instagram_username": "creator"}
    generation = {"render_job_id": "export-1", "status": "completed", "generated_packages": {"instagram_reels": {"caption": "Reviewed", "hashtags": []}}, "edited_packages": {}}
    created = {"id": "upload-1", "render_job_id": "export-1", "generation_id": "generation-1", "page_id": "page123", "page_name": "Page", "instagram_user_id": "ig123", "instagram_username": "creator", "status": "queued", "progress": 0, "stage": "queued", "media_id": None, "container_id": None, "permalink": None, "error_message": None, "created_at": "2026-11-23T00:00:00Z", "completed_at": None}
    queued = []
    monkeypatch.setattr(api.instagram_r2_storage, "configured", lambda: True)
    monkeypatch.setattr(api, "_export_path", lambda _job: tmp_path / "export.mp4")
    monkeypatch.setattr(api.instagram_auth, "selected_account", lambda _account: account)
    monkeypatch.setattr(api.social_content_store, "get", lambda _generation: generation)
    monkeypatch.setattr(api.instagram_upload_store, "create", lambda **kwargs: (queued.append(("create", kwargs)) or created))
    monkeypatch.setattr(api, "enqueue", lambda *args: queued.append(("enqueue", args)))

    response = client.post("/api/social/instagram/exports/export-1/uploads", json={
        "approved": True, "generation_id": "generation-1", "instagram_user_id": "ig123",
    })
    assert response.status_code == 202
    assert "diagnostic_variant" not in response.json()
    assert queued[0][1]["generation_id"] == "generation-1"
    assert len(queued[1][1]) == 4


def test_database_migration_removes_legacy_instagram_diagnostic_column(client):
    from app.db.database import connect, initialize_database

    with connect() as db:
        db.execute("ALTER TABLE instagram_uploads ADD COLUMN diagnostic_variant TEXT")
    initialize_database()
    with connect() as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(instagram_uploads)").fetchall()}
    assert "diagnostic_variant" not in columns
    assert {"container_id", "r2_object_key"}.issubset(columns)
