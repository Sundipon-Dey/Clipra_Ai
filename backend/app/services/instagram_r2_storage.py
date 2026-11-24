"""Temporary public-fetch storage for Instagram Reels, backed by Cloudflare R2."""
from __future__ import annotations

import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from app.core.config import settings
from app.services.storage import managed_directory

logger = logging.getLogger(__name__)
PRESIGNED_URL_TTL_SECONDS = 2 * 60 * 60
OBJECT_PREFIX = "ig-reels/"


class R2StorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class PresignedObjectUrls:
    """Method-specific URLs for the same uploaded object."""

    get_url: str
    head_url: str


def configured() -> bool:
    return all((settings.r2_account_id, settings.r2_bucket, settings.r2_access_key_id, settings.r2_secret_access_key))


def _client():
    if not configured():
        raise R2StorageError("Configure R2_ACCOUNT_ID, R2_BUCKET, R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY in backend/.env before publishing Instagram Reels.")
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise R2StorageError("The pinned boto3 dependency is missing. Install backend requirements and restart CLIPRA.") from exc
    endpoint = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="auto",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 2, "mode": "standard"}),
    )


def new_object_key() -> str:
    return f"{OBJECT_PREFIX}{uuid4()}.mp4"


def upload_object(path: Path, key: str, *, progress_callback=None) -> str:
    if not key.startswith(OBJECT_PREFIX) or not key.endswith(".mp4"):
        raise R2StorageError("Instagram temporary R2 objects must use the ig-reels/ prefix and an MP4 filename.")
    size = path.stat().st_size
    if size <= 0:
        raise R2StorageError("The completed Instagram export is empty.")
    try:
        from boto3.s3.transfer import TransferConfig

        client = _client()
        client.upload_file(
            str(path), settings.r2_bucket, key,
            ExtraArgs={"ContentType": "video/mp4"},
            Callback=progress_callback,
            Config=TransferConfig(multipart_threshold=32 * 1024**2, multipart_chunksize=8 * 1024**2, max_concurrency=2),
        )
        params = {"Bucket": settings.r2_bucket, "Key": key}
        return PresignedObjectUrls(
            get_url=client.generate_presigned_url(
                "get_object", Params=params, ExpiresIn=PRESIGNED_URL_TTL_SECONDS,
            ),
            # SigV4 presigns an HTTP method. A GET-signed URL is not a valid
            # HEAD request, so verify the same object with its own HEAD URL.
            head_url=client.generate_presigned_url(
                "head_object", Params=params, ExpiresIn=PRESIGNED_URL_TTL_SECONDS,
            ),
        )
    except R2StorageError:
        raise
    except Exception as exc:
        logger.warning("Cloudflare R2 upload or URL signing failed (error type %s).", type(exc).__name__)
        raise R2StorageError("CLIPRA could not upload the temporary Reel to Cloudflare R2. Check the R2 bucket and credentials.") from exc


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def verify_presigned_url(url: str, expected_size: int) -> None:
    """Verify the method-specific signed HEAD URL for the object, without redirects."""
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "CLIPRA.AI/1.0"})
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            status = response.status
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            content_length = response.headers.get("Content-Length")
            if status != 200:
                raise R2StorageError(f"The signed R2 URL returned HTTP {status} to HEAD; Instagram upload was stopped.")
            if content_type != "video/mp4":
                raise R2StorageError(f"The signed R2 URL returned Content-Type {content_type or '(missing)'}, expected video/mp4.")
            if content_length is None or int(content_length) != expected_size:
                raise R2StorageError("The signed R2 URL returned a Content-Length that does not match the local export.")
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise R2StorageError(f"The signed R2 URL redirects (HTTP {exc.code}); Instagram requires a direct media response.") from exc
        # R2 commonly identifies signing/configuration problems in its XML body.
        # Extract only safe diagnostic fields and never echo the signed request URL.
        try:
            import xml.etree.ElementTree as ET

            root = ET.fromstring(exc.read(4096))
            code = root.findtext("Code")
            message = root.findtext("Message")
        except (ET.ParseError, OSError, ValueError):
            code, message = None, None
        detail = ": ".join(value for value in (code, message) if value)
        suffix = f" ({detail})" if detail else ""
        raise R2StorageError(f"The signed R2 URL HEAD check returned HTTP {exc.code}{suffix}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise R2StorageError("CLIPRA could not verify the signed R2 URL with a direct HEAD request.") from exc


def delete_object(key: str) -> None:
    if not key.startswith(OBJECT_PREFIX):
        raise R2StorageError("Refusing to delete an R2 object outside the ig-reels/ prefix.")
    try:
        _client().delete_object(Bucket=settings.r2_bucket, Key=key)
    except Exception as exc:
        logger.warning("Cloudflare R2 cleanup failed for key %s (error type %s); lifecycle cleanup remains enabled.", key, type(exc).__name__)
        raise R2StorageError("CLIPRA could not immediately delete the temporary R2 object; the bucket lifecycle rule will remove it.") from exc


def display_url_without_signature(url: str) -> str:
    """Return a useful URL location without any presigned query parameters."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return "(invalid URL)"
    return f"{parts.scheme}://{parts.netloc}{parts.path}?<presigned query redacted>"


def make_smoke_test_file() -> Path:
    """Create a tiny, disposable object body with an MP4 content type for R2 checks."""
    directory = managed_directory("temp/instagram-r2-check")
    path = directory / f"r2-check-{uuid4().hex}.mp4"
    path.write_bytes(b"CLIPRA R2 connectivity test; this is not a playable video.\n")
    return path
