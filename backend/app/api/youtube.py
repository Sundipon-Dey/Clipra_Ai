"""YouTube account connection and explicit upload endpoints."""
from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, HTTPException, status

from app.models.schemas import YouTubeStatusOut, YouTubeUploadOut, YouTubeUploadStart
from app.services import social_content_store, youtube_auth, youtube_upload_store
from app.services.render_store import get as get_render
from app.services.storage import StoragePathError, managed_path
from app.services.youtube_upload_queue import enqueue

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/social/youtube", tags=["YouTube publishing"])


def _out(record: dict) -> YouTubeUploadOut:
    video_id = record.get("video_id")
    return YouTubeUploadOut(**record, video_url=f"https://www.youtube.com/watch?v={video_id}" if video_id else None)


def _export_path(render_job_id: str):
    job = get_render(render_job_id)
    if not job or job.get("kind") != "export":
        raise HTTPException(404, "Export version not found.")
    if job.get("status") != "completed" or not job.get("output_relative_path"):
        raise HTTPException(409, "Only a completed export can be uploaded to YouTube.")
    try:
        path = managed_path(job["output_relative_path"], must_exist=True)
    except (FileNotFoundError, StoragePathError, OSError, ValueError) as exc:
        raise HTTPException(410, "The completed export is missing from managed storage.") from exc
    if not path.is_file() or path.suffix.lower() != ".mp4" or path.stat().st_size <= 0:
        raise HTTPException(410, "The completed MP4 is missing or empty.")
    return path


@router.get("/status", response_model=YouTubeStatusOut)
def get_status() -> YouTubeStatusOut:
    return YouTubeStatusOut(**youtube_auth.status())


@router.post("/connect", status_code=status.HTTP_202_ACCEPTED)
def connect_account() -> dict[str, str]:
    try:
        message = youtube_auth.begin_connect()
    except youtube_auth.YouTubeAuthError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"status": "authorization_started", "message": message}


@router.delete("/connection", response_model=YouTubeStatusOut)
def disconnect_account() -> YouTubeStatusOut:
    youtube_auth.disconnect()
    return YouTubeStatusOut(**youtube_auth.status())


@router.get("/exports/{render_job_id}/uploads", response_model=list[YouTubeUploadOut])
def list_uploads(render_job_id: str) -> list[YouTubeUploadOut]:
    _export_path(render_job_id)
    return [_out(record) for record in youtube_upload_store.list_for_render(render_job_id)]


@router.post("/exports/{render_job_id}/uploads", response_model=YouTubeUploadOut, status_code=status.HTTP_202_ACCEPTED)
def start_upload(render_job_id: str, payload: YouTubeUploadStart) -> YouTubeUploadOut:
    if not youtube_auth.status()["connected"]:
        raise HTTPException(409, "Connect your YouTube account before uploading.")
    path = _export_path(render_job_id)
    generation = social_content_store.get(payload.generation_id)
    if not generation or generation.get("render_job_id") != render_job_id or generation.get("status") != "completed":
        raise HTTPException(409, "Generate and review YouTube Shorts content for this exact export before uploading.")
    # The store keeps the immutable generated packages and user edits separately.
    # Apply edits over generated content, matching the Social Content API response.
    packages = dict(generation.get("generated_packages") or {})
    packages.update(generation.get("edited_packages") or {})
    package = packages.get("youtube_shorts")
    if not isinstance(package, dict):
        raise HTTPException(409, "The saved YouTube Shorts package is unavailable. Generate or save it before uploading.")
    try:
        record = youtube_upload_store.create(render_job_id=render_job_id, generation_id=payload.generation_id, privacy_status=payload.privacy_status)
    except (RuntimeError, sqlite3.IntegrityError) as exc:
        raise HTTPException(409, str(exc)) from exc
    # The request is explicit; a restart marks the job interrupted rather than sending it again.
    enqueue(record["id"], path, package)
    return _out(record)


@router.get("/uploads/{upload_id}", response_model=YouTubeUploadOut)
def get_upload(upload_id: str) -> YouTubeUploadOut:
    record = youtube_upload_store.get(upload_id)
    if not record:
        raise HTTPException(404, "YouTube upload was not found.")
    return _out(record)
