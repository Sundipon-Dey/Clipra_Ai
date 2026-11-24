"""Explicitly approved Instagram Reels publishing through a temporary R2 URL."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import settings
from app.services import facebook_auth, instagram_auth, instagram_r2_storage, instagram_upload_store as store
from app.services.facebook_auth import FacebookAuthError

logger = logging.getLogger(__name__)
INSTAGRAM_GRAPH_API_VERSION = "v25.0"
PROCESSING_TIMEOUT_SECONDS = 20 * 60
PROCESSING_POLL_SECONDS = 30
MAX_REEL_BYTES = 300 * 1024**2
MAX_VIDEO_BITRATE = 25_000_000


class InstagramUploadError(RuntimeError):
    pass


class InstagramMetaError(InstagramUploadError):
    def __init__(self, message: str, *, http_status: int | None):
        super().__init__(message)
        self.http_status = http_status


class InstagramContainerTerminalError(InstagramUploadError):
    pass


class InstagramProcessingTimeout(InstagramUploadError):
    pass


def _redact_meta_text(value: str) -> str:
    text = re.sub(r"(?i)(access[_-]?token[\"'=:\s]+)[^&\s,\"}]+", r"\1[redacted]", value)
    text = re.sub(r"\bEAA[A-Za-z0-9_-]{20,}\b", "[redacted token]", text)
    # If Meta echoes a video_url, never put any part of its presigned query in logs/UI.
    def redact_url(match: re.Match[str]) -> str:
        raw = match.group(0)
        parsed = urlsplit(raw.rstrip(".,);]"))
        if any(name.lower().startswith("x-amz-") for name, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)):
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?[presigned query redacted]"
        return raw
    text = re.sub(r"https?://[^\s\"'<>]+", redact_url, text)
    text = re.sub(r"(?i)([?&](?:X-Amz-[A-Za-z0-9_-]+|access_token)=)[^&\s\"\\]+", r"\1[redacted]", text)
    return text


def _log_meta_response(endpoint: str, status: int | str, elapsed_ms: int, trace_id: str | None, raw_body: bytes) -> str:
    body = _redact_meta_text(raw_body.decode("utf-8", errors="replace"))
    logger.info(
        "Instagram Meta API endpoint=%s status=%s elapsed_ms=%s x-fb-trace-id=%s response_body=%s",
        endpoint, status, elapsed_ms, trace_id or "(missing)", body or "(empty)",
    )
    return body


def _send_graph(request: urllib.request.Request, endpoint: str) -> dict:
    started = time.monotonic()
    try:
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw_body = response.read()
                status = response.status
                trace_id = response.headers.get("x-fb-trace-id")
        except urllib.error.HTTPError as exc:
            raw_body = exc.read()
            trace_id = exc.headers.get("x-fb-trace-id") if exc.headers else None
            elapsed_ms = round((time.monotonic() - started) * 1000)
            body = _log_meta_response(endpoint, exc.code, elapsed_ms, trace_id, raw_body)
            raise InstagramMetaError(
                f"Meta API {endpoint} returned HTTP {exc.code}. Response body: {body or '(empty)'}. "
                f"x-fb-trace-id: {trace_id or '(missing)'}.",
                http_status=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            _log_meta_response(endpoint, "no response", elapsed_ms, None, b"")
            raise InstagramMetaError(
                f"No HTTP response was received from Meta for {endpoint}. Check the Instagram job before retrying.",
                http_status=None,
            ) from exc
        elapsed_ms = round((time.monotonic() - started) * 1000)
        body = _log_meta_response(endpoint, status, elapsed_ms, trace_id, raw_body)
        try:
            result = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise InstagramMetaError(
                f"Meta API {endpoint} returned HTTP {status} with an unreadable response body: {body}",
                http_status=status,
            ) from exc
        if not isinstance(result, dict):
            raise InstagramMetaError(
                f"Meta API {endpoint} returned HTTP {status} with an unexpected response: {body}",
                http_status=status,
            )
        if result.get("error"):
            raise InstagramMetaError(
                f"Meta API {endpoint} returned HTTP {status}. Response body: {body}.",
                http_status=status,
            )
        return result
    except InstagramMetaError:
        raise


def _graph_url(path: str) -> str:
    return f"https://graph.facebook.com/{INSTAGRAM_GRAPH_API_VERSION}/{path.lstrip('/')}"


def _graph_request(path: str, fields: dict[str, str]) -> dict:
    safe_path = "/".join(urllib.parse.quote(part, safe="") for part in path.strip("/").split("/"))
    endpoint = f"POST /{INSTAGRAM_GRAPH_API_VERSION}/{safe_path}"
    request = urllib.request.Request(
        _graph_url(path), data=urllib.parse.urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "CLIPRA.AI/1.0"}, method="POST",
    )
    return _send_graph(request, endpoint)


def _graph_get(path: str, fields: dict[str, str]) -> dict:
    safe_path = "/".join(urllib.parse.quote(part, safe="") for part in path.strip("/").split("/"))
    endpoint = f"GET /{INSTAGRAM_GRAPH_API_VERSION}/{safe_path}"
    query = urllib.parse.urlencode(fields)
    request = urllib.request.Request(f"{_graph_url(path)}?{query}", headers={"User-Agent": "CLIPRA.AI/1.0"}, method="GET")
    return _send_graph(request, endpoint)


def _caption(package: dict) -> str:
    caption = str(package.get("caption") or package.get("opening_hook") or "").strip()
    hashtags = [str(value).strip() for value in package.get("hashtags", []) if str(value).strip()]
    hashtag_line = " ".join(value if value.startswith("#") else f"#{value}" for value in hashtags[:30])
    result = "\n\n".join(part for part in (caption, hashtag_line) if part)
    if len(result) > 2200:
        raise InstagramUploadError("The Instagram caption exceeds 2,200 characters. Shorten the caption or hashtag list and save the package.")
    return result


def _probe_reel_file(path: Path) -> dict:
    import shutil
    import subprocess

    ffprobe = settings.ffprobe_path or shutil.which("ffprobe")
    if not ffprobe:
        raise InstagramUploadError("FFprobe is unavailable, so CLIPRA cannot verify Instagram's Reel limits.")
    command = [ffprobe, "-v", "error", "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height,avg_frame_rate,sample_rate,bit_rate", "-of", "json", str(path)]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=settings.ffprobe_timeout_seconds)
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise InstagramUploadError("CLIPRA could not verify the completed export with FFprobe.") from exc


def _validate_reel_file(path: Path) -> dict:
    size = path.stat().st_size
    if size <= 0:
        raise InstagramUploadError("The completed export is empty.")
    if size > MAX_REEL_BYTES:
        raise InstagramUploadError("Instagram Reels API accepts videos up to 300 MB. Choose a smaller export resolution or bitrate.")
    probe = _probe_reel_file(path)
    duration = float(probe.get("format", {}).get("duration", 0))
    if not 3 <= duration <= 900:
        raise InstagramUploadError("Instagram Reels must be between 3 seconds and 15 minutes long.")
    video = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"), None)
    if not video or video.get("codec_name") not in {"h264", "hevc"}:
        raise InstagramUploadError("Instagram Reels require an H.264 or HEVC video stream.")
    audio = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"), None)
    if audio and (audio.get("codec_name") != "aac" or int(audio.get("sample_rate") or 0) > 48000):
        raise InstagramUploadError("Instagram Reels require AAC audio at 48 kHz or lower.")
    if int(video.get("width") or 0) > 1920:
        raise InstagramUploadError("Instagram Reels support a maximum video width of 1,920 pixels.")
    if int(video.get("bit_rate") or 0) > MAX_VIDEO_BITRATE:
        raise InstagramUploadError("Instagram Reels support video bitrate up to 25 Mbps.")
    try:
        numerator, denominator = str(video.get("avg_frame_rate") or "0/0").split("/", 1)
        frame_rate = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        frame_rate = 0
    if frame_rate and not 23 <= frame_rate <= 60:
        raise InstagramUploadError("Instagram Reels require a frame rate between 23 and 60 fps.")
    return probe


def _wait_until_ready(container_id: str, token: str, upload_id: str) -> None:
    deadline = time.monotonic() + PROCESSING_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        elapsed = PROCESSING_TIMEOUT_SECONDS - max(0, deadline - time.monotonic())
        store.progress(upload_id, min(0.88, 0.58 + 0.30 * elapsed / PROCESSING_TIMEOUT_SECONDS), "processing_video")
        result = _graph_get(container_id, {"fields": "status_code,status", "access_token": token})
        state = str(result.get("status_code") or "").upper()
        if state == "FINISHED":
            return
        if state in {"ERROR", "EXPIRED"}:
            detail = _redact_meta_text(json.dumps(result, ensure_ascii=False))
            raise InstagramContainerTerminalError(f"Instagram container reached {state}. Meta status: {detail}")
        time.sleep(min(PROCESSING_POLL_SECONDS, max(0, deadline - time.monotonic())))
    raise InstagramProcessingTimeout("Instagram did not finish processing the Reel within 20 minutes. Its R2 object was retained while the container could still be processing; the ig-reels lifecycle rule will remove it after one day.")


def run(upload_id: str, video_path: Path, package: dict, instagram_user_id: str) -> None:
    if not store.start(upload_id):
        return
    object_key: str | None = None
    safe_to_delete = True
    try:
        account = instagram_auth.selected_account(instagram_user_id)
        if not account:
            raise InstagramUploadError("The selected Instagram account is unavailable. Reconnect Meta and choose the linked professional account.")
        page = facebook_auth.selected_page(account["page_id"])
        if not page or page.get("instagram_user_id") != instagram_user_id:
            raise InstagramUploadError("The selected Instagram account is no longer linked to this Page. Reconnect Meta and try again.")

        _validate_reel_file(video_path)
        size = video_path.stat().st_size
        object_key = instagram_r2_storage.new_object_key()
        store.set_r2_object(upload_id, object_key)
        uploaded_bytes = 0
        progress_lock = threading.Lock()

        def on_r2_progress(delta: int) -> None:
            nonlocal uploaded_bytes
            with progress_lock:
                uploaded_bytes += delta
                progress = 0.02 + 0.46 * min(1, uploaded_bytes / size)
            store.progress(upload_id, progress, "uploading_to_r2")

        store.progress(upload_id, 0.01, "uploading_to_r2")
        presigned_urls = instagram_r2_storage.upload_object(video_path, object_key, progress_callback=on_r2_progress)
        store.progress(upload_id, 0.49, "verifying_r2_url")
        instagram_r2_storage.verify_presigned_url(presigned_urls.head_url, size)

        token = page["access_token"]
        caption = _caption(package)
        store.progress(upload_id, 0.50, "creating_container")
        try:
            container = _graph_request(f"{instagram_user_id}/media", {
                "media_type": "REELS", "video_url": presigned_urls.get_url, "share_to_feed": "true",
                "caption": caption, "access_token": token,
            })
        except InstagramMetaError as exc:
            if exc.http_status is None:
                # Meta may have accepted the create request before the connection failed.
                safe_to_delete = False
            raise
        container_id = str(container.get("id") or "")
        if not container_id or not container_id.isdigit():
            # A 2xx create with no usable ID leaves the remote container state unknown.
            safe_to_delete = False
            raise InstagramUploadError("Meta created no usable Instagram Reel container ID. The temporary R2 object was retained for lifecycle cleanup.")
        safe_to_delete = False
        store.set_container(upload_id, container_id)

        try:
            _wait_until_ready(container_id, token, upload_id)
        except InstagramContainerTerminalError:
            safe_to_delete = True
            raise
        # Keep the object until publishing is confirmed or a terminal HTTP response arrives.
        store.progress(upload_id, 0.92, "publishing_reel")
        try:
            published = _graph_request(f"{instagram_user_id}/media_publish", {"creation_id": container_id, "access_token": token})
        except InstagramMetaError as exc:
            # A response is a terminal result for this attempt; no response is ambiguous.
            safe_to_delete = exc.http_status is not None
            raise
        media_id = str(published.get("id") or "")
        if not media_id:
            raise InstagramUploadError("Meta returned no Instagram media ID after publishing. Check Instagram before retrying.")
        safe_to_delete = True
        permalink = None
        try:
            details = _graph_get(media_id, {"fields": "permalink", "access_token": token})
            permalink = str(details.get("permalink") or "") or None
        except InstagramUploadError as exc:
            logger.warning("Instagram media %s was published, but permalink lookup failed: %s", media_id, exc)
        store.finish(upload_id, media_id, permalink)
    except (FacebookAuthError, InstagramUploadError, instagram_r2_storage.R2StorageError) as exc:
        store.fail(upload_id, str(exc))
    except Exception:
        logger.exception("Unexpected Instagram Reels upload failure for job %s", upload_id)
        store.fail(upload_id, "An unexpected local error interrupted this Instagram upload. Check Instagram before retrying.")
    finally:
        if object_key and safe_to_delete:
            try:
                instagram_r2_storage.delete_object(object_key)
            except instagram_r2_storage.R2StorageError as exc:
                # R2 lifecycle cleanup is the safety net; cleanup never changes publish outcome.
                logger.warning("Instagram temporary object cleanup failed for upload %s: %s", upload_id, exc)
        elif object_key:
            logger.warning("Instagram R2 object %s retained because its Meta container may still be processing; the one-day lifecycle rule will clean it up.", object_key)
