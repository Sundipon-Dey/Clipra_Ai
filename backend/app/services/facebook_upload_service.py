"""Explicitly approved Facebook Page Reels upload using Meta's Graph/rupload APIs."""
from __future__ import annotations

import http.client
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import settings
from app.services import facebook_auth, facebook_upload_store as store
from app.services.facebook_auth import FacebookAuthError

logger = logging.getLogger(__name__)
CHUNK_BYTES = 8 * 1024 * 1024


class FacebookUploadError(RuntimeError):
    pass


def _graph_url(path: str) -> str:
    return f"https://graph.facebook.com/{settings.facebook_graph_api_version}/{path.lstrip('/')}"


def _graph_post(path: str, fields: dict[str, str]) -> dict:
    request = urllib.request.Request(_graph_url(path), data=urllib.parse.urlencode(fields).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "CLIPRA.AI/1.0"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read(1024 * 1024))
        if not isinstance(result, dict):
            raise FacebookUploadError("Meta returned an unexpected upload response.")
        if result.get("error"):
            raise FacebookUploadError("Meta rejected the Facebook Reels upload. Check Page permissions and try again.")
        return result
    except urllib.error.HTTPError as exc:
        # Never include the raw response or request URL; Graph responses/URLs may contain sensitive tokens.
        try:
            error = json.loads(exc.read(4096)).get("error", {})
            message = str(error.get("message") or "")
        except (json.JSONDecodeError, AttributeError):
            message = ""
        raise FacebookUploadError(f"Meta rejected the Facebook Reels request (HTTP {exc.code}). {message[:350] or 'Check Page permissions and the app configuration.'}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise FacebookUploadError("The connection to Meta failed. Check your Page before retrying; the Reel may have been published.") from exc


def _clean_description(package: dict) -> tuple[str, str]:
    caption = str(package.get("caption") or "").strip()
    hook = str(package.get("opening_hook") or "").strip()
    if not caption and not hook:
        raise FacebookUploadError("Add a Facebook Reels caption before publishing.")
    hashtags = [str(item).strip() for item in package.get("hashtags", []) if str(item).strip()]
    hashtag_line = " ".join(item if item.startswith("#") else f"#{item}" for item in hashtags[:30])
    description = "\n\n".join(part for part in (caption or hook, hashtag_line) if part)
    if len(description) > 5000:
        raise FacebookUploadError("The Facebook Reels caption is too long. Shorten it and save the package.")
    return hook[:100], description


def _transfer(upload_url: str, token: str, path: Path, upload_id: str) -> None:
    parsed = urlsplit(upload_url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".facebook.com"):
        raise FacebookUploadError("Meta returned an invalid secure upload address.")
    size = path.stat().st_size
    if size <= 0:
        raise FacebookUploadError("The completed export is empty.")
    connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=240)
    try:
        connection.putrequest("POST", parsed.path + (f"?{parsed.query}" if parsed.query else ""))
        connection.putheader("Authorization", f"OAuth {token}")
        connection.putheader("offset", "0")
        connection.putheader("file_size", str(size))
        connection.putheader("Content-Type", "application/octet-stream")
        connection.putheader("Content-Length", str(size))
        connection.endheaders()
        sent = 0
        with path.open("rb") as video:
            while sent < size:
                chunk = video.read(min(CHUNK_BYTES, size - sent))
                if not chunk:
                    raise FacebookUploadError("The completed export changed while uploading; the upload was stopped.")
                connection.send(chunk)
                sent += len(chunk)
                store.progress(upload_id, 0.05 + 0.8 * sent / size, "uploading_video")
        response = connection.getresponse()
        raw = response.read(1024 * 1024)
        try:
            result = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise FacebookUploadError("Meta returned an unreadable upload response. Check your Page before retrying.") from exc
        if response.status not in {200, 201} or not result.get("success", True):
            raise FacebookUploadError(f"Meta could not receive the video file (HTTP {response.status}). Check the export and Page permissions.")
    except FacebookUploadError:
        raise
    except (OSError, http.client.HTTPException, TimeoutError) as exc:
        raise FacebookUploadError("The video transfer to Meta failed. Check your Facebook Page before retrying; the Reel may have reached Meta.") from exc
    finally:
        connection.close()


def run(upload_id: str, video_path: Path, package: dict, page_id: str) -> None:
    if not store.start(upload_id):
        return
    try:
        record = store.get(upload_id)
        page = facebook_auth.selected_page(page_id)
        if not record or not page:
            raise FacebookUploadError("The selected Facebook Page connection is unavailable. Reconnect Facebook and try again.")
        title, description = _clean_description(package)
        size = video_path.stat().st_size
        if size <= 0:
            raise FacebookUploadError("The completed export is empty.")
        token = page["access_token"]
        started = _graph_post(f"{page_id}/video_reels", {"upload_phase": "start", "access_token": token})
        video_id, upload_url = str(started.get("video_id") or ""), str(started.get("upload_url") or "")
        if not video_id or not upload_url:
            raise FacebookUploadError("Meta did not start a Reel upload session.")
        store.progress(upload_id, 0.05, "uploading_video")
        _transfer(upload_url, token, video_path, upload_id)
        store.progress(upload_id, 0.9, "publishing_reel")
        finished = _graph_post(f"{page_id}/video_reels", {
            "upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED",
            "description": description, "title": title, "access_token": token,
        })
        if finished.get("success") is False:
            raise FacebookUploadError("Meta received the video but did not confirm publishing. Check your Page's Reels before retrying.")
        store.finish(upload_id, video_id, str(finished.get("post_id") or "") or None)
    except (FacebookAuthError, FacebookUploadError) as exc:
        store.fail(upload_id, str(exc))
    except Exception:
        logger.exception("Unexpected Facebook Reels upload failure for job %s", upload_id)
        store.fail(upload_id, "An unexpected local error interrupted this upload. Check your Facebook Page before retrying.")
