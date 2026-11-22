"""User-approved, resumable YouTube Data API video uploads."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.services import youtube_auth, youtube_upload_store as store
from app.services.youtube_auth import YouTubeAuthError

logger = logging.getLogger(__name__)
CHUNK_BYTES = 8 * 1024 * 1024
UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"


class YouTubeUploadError(RuntimeError):
    pass


def _request(request: urllib.request.Request):
    try:
        return urllib.request.urlopen(request, timeout=180)
    except urllib.error.HTTPError as exc:
        # A 308 is the normal response while a resumable upload is incomplete.
        if exc.code == 308:
            return exc
        body = exc.read(4096).decode("utf-8", errors="replace")
        logger.warning("YouTube API upload request failed with HTTP %s", exc.code)
        try:
            error_payload = json.loads(body)
            reasons = {item.get("reason") for item in error_payload.get("error", {}).get("errors", []) if isinstance(item, dict)}
        except (json.JSONDecodeError, AttributeError, TypeError):
            reasons = set()
        if "youtubeSignupRequired" in reasons:
            raise YouTubeUploadError(
                "YouTube says the Google account authorized in CLIPRA is not linked to an API-available YouTube channel. "
                "Open YouTube in your browser, verify that this same Google account can switch to the intended channel, "
                "then disconnect YouTube in CLIPRA and reconnect, choosing the correct Google account. "
                "If the channel is a Brand Account and this still happens, its delegated channel permissions may not be accepted by the YouTube Data API."
            ) from exc
        raise YouTubeUploadError(f"YouTube rejected the upload request (HTTP {exc.code}). Check the video and account in YouTube Studio, then review the connection and try again. {body[:500]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise YouTubeUploadError("The YouTube upload connection failed. Check your internet connection and YouTube Studio before retrying; the video may have reached YouTube.") from exc


def _response_json(response) -> dict[str, Any]:
    try:
        raw = response.read(2 * 1024 * 1024)
        return json.loads(raw) if raw else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise YouTubeUploadError("YouTube returned an unreadable upload response. Check YouTube Studio before retrying.") from exc


def _clean_metadata(package: dict[str, Any]) -> dict[str, Any]:
    title = str(package.get("title") or "").strip()
    description = str(package.get("description") or "").strip()
    if not title:
        raise YouTubeUploadError("Add a YouTube title before uploading.")
    if len(title) > 100:
        raise YouTubeUploadError("YouTube titles can be up to 100 characters.")
    if len(description) > 5000:
        raise YouTubeUploadError("YouTube descriptions can be up to 5,000 characters.")
    hashtags = [str(value).strip() for value in package.get("hashtags", []) if str(value).strip()]
    tags = [str(value).strip().lstrip("#") for value in package.get("tags", []) if str(value).strip()]
    all_tags = list(dict.fromkeys([*tags, *(value.lstrip("#") for value in hashtags)]))[:20]
    if sum(len(tag) for tag in all_tags) > 500:
        raise YouTubeUploadError("The combined YouTube tags are too long. Shorten the tags and save the package.")
    if hashtags:
        hashtag_line = " ".join(value if value.startswith("#") else f"#{value}" for value in hashtags[:12])
        if hashtag_line not in description:
            description = f"{description}\n\n{hashtag_line}".strip()
    return {"title": title, "description": description[:5000], "tags": all_tags}


def run(upload_id: str, video_path: Path, package: dict[str, Any]) -> None:
    if not store.start(upload_id):
        return
    try:
        record = store.get(upload_id)
        if not record:
            raise YouTubeUploadError("YouTube upload record was not found.")
        metadata = _clean_metadata(package)
        access_token = youtube_auth.access_token()
        size_bytes = video_path.stat().st_size
        if size_bytes <= 0:
            raise YouTubeUploadError("The completed export is empty.")
        body = json.dumps({
            "snippet": {"title": metadata["title"], "description": metadata["description"], "tags": metadata["tags"], "categoryId": "22"},
            "status": {"privacyStatus": record["privacy_status"]},
        }, ensure_ascii=False).encode("utf-8")
        start_request = urllib.request.Request(
            f"{UPLOAD_ENDPOINT}?{urllib.parse.urlencode({'uploadType': 'resumable', 'part': 'snippet,status'})}",
            data=body,
            headers={
                "Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(size_bytes), "X-Upload-Content-Type": "video/mp4",
            }, method="POST",
        )
        response = _request(start_request)
        with response:
            upload_url = response.headers.get("Location")
        parsed_upload = urlsplit(upload_url or "")
        if parsed_upload.scheme != "https" or not (parsed_upload.hostname or "").endswith(".googleapis.com"):
            raise YouTubeUploadError("Google did not return a valid secure resumable upload URL.")

        sent = 0
        with video_path.open("rb") as video:
            while sent < size_bytes:
                chunk = video.read(CHUNK_BYTES)
                if not chunk:
                    raise YouTubeUploadError("The completed export changed while uploading; the upload was stopped.")
                end = sent + len(chunk) - 1
                chunk_request = urllib.request.Request(upload_url, data=chunk, headers={
                    "Authorization": f"Bearer {access_token}", "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)), "Content-Range": f"bytes {sent}-{end}/{size_bytes}",
                }, method="PUT")
                chunk_response = _request(chunk_request)
                status_code = getattr(chunk_response, "status", getattr(chunk_response, "code", 308))
                with chunk_response:
                    if status_code in {200, 201}:
                        result = _response_json(chunk_response)
                        video_id = str(result.get("id") or "")
                        if not video_id:
                            raise YouTubeUploadError("YouTube completed the upload but did not return a video ID. Check YouTube Studio before retrying.")
                        store.finish(upload_id, video_id)
                        return
                    if status_code != 308:
                        raise YouTubeUploadError(f"YouTube returned an unexpected upload status ({status_code}). Check YouTube Studio before retrying.")
                sent += len(chunk)
                store.progress(upload_id, sent / size_bytes)
        raise YouTubeUploadError("YouTube did not confirm completion. Check YouTube Studio before retrying.")
    except (YouTubeAuthError, YouTubeUploadError) as exc:
        store.fail(upload_id, str(exc))
    except Exception:
        logger.exception("Unexpected YouTube upload failure for job %s", upload_id)
        store.fail(upload_id, "An unexpected local error interrupted this upload. Check YouTube Studio before retrying.")


