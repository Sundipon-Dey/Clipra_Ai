"""Facebook Page authorization and explicit Reels publishing endpoints."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, status

from app.models.schemas import FacebookStatusOut, FacebookUploadOut, FacebookUploadStart
from app.services import facebook_auth, facebook_upload_store, social_content_store
from app.services.facebook_auth import FacebookAuthError
from app.services.facebook_upload_queue import enqueue
from app.services.render_store import get as get_render
from app.services.storage import StoragePathError, managed_path

router = APIRouter(prefix="/api/social/facebook", tags=["Facebook publishing"])


def _export_path(render_job_id: str):
    job = get_render(render_job_id)
    if not job or job.get("kind") != "export":
        raise HTTPException(404, "Export version not found.")
    if job.get("status") != "completed" or not job.get("output_relative_path"):
        raise HTTPException(409, "Only a completed export can be published to Facebook.")
    try:
        path = managed_path(job["output_relative_path"], must_exist=True)
    except (FileNotFoundError, StoragePathError, OSError, ValueError) as exc:
        raise HTTPException(410, "The completed export is missing from managed storage.") from exc
    if not path.is_file() or path.suffix.lower() != ".mp4" or path.stat().st_size <= 0:
        raise HTTPException(410, "The completed MP4 is missing or empty.")
    return path


def _out(record: dict) -> FacebookUploadOut:
    video_id = record.get("video_id")
    return FacebookUploadOut(**record, video_url=f"https://www.facebook.com/reel/{video_id}" if video_id else None)


@router.get("/status", response_model=FacebookStatusOut)
def get_status() -> FacebookStatusOut:
    return FacebookStatusOut(**facebook_auth.status())


@router.post("/connect", status_code=status.HTTP_202_ACCEPTED)
def connect_account() -> dict[str, str]:
    try:
        message = facebook_auth.begin_connect()
    except FacebookAuthError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"status": "authorization_started", "message": message}


@router.delete("/connection", response_model=FacebookStatusOut)
def disconnect_account() -> FacebookStatusOut:
    facebook_auth.disconnect()
    return FacebookStatusOut(**facebook_auth.status())


@router.get("/exports/{render_job_id}/uploads", response_model=list[FacebookUploadOut])
def list_uploads(render_job_id: str) -> list[FacebookUploadOut]:
    _export_path(render_job_id)
    return [_out(record) for record in facebook_upload_store.list_for_render(render_job_id)]


@router.post("/exports/{render_job_id}/uploads", response_model=FacebookUploadOut, status_code=status.HTTP_202_ACCEPTED)
def start_upload(render_job_id: str, payload: FacebookUploadStart) -> FacebookUploadOut:
    path = _export_path(render_job_id)
    page = facebook_auth.selected_page(payload.page_id)
    if not page:
        raise HTTPException(409, "Connect Facebook and choose a Page you manage before publishing.")
    generation = social_content_store.get(payload.generation_id)
    if not generation or generation.get("render_job_id") != render_job_id or generation.get("status") != "completed":
        raise HTTPException(409, "Generate and review Facebook Reels content for this exact export before publishing.")
    packages = dict(generation.get("generated_packages") or {})
    packages.update(generation.get("edited_packages") or {})
    package = packages.get("facebook_reels")
    if not isinstance(package, dict):
        raise HTTPException(409, "The saved Facebook Reels package is unavailable. Generate or save it before publishing.")
    try:
        record = facebook_upload_store.create(render_job_id=render_job_id, generation_id=payload.generation_id,
                                              page_id=page["id"], page_name=page["name"])
    except (RuntimeError, sqlite3.IntegrityError) as exc:
        raise HTTPException(409, str(exc)) from exc
    enqueue(record["id"], path, package, page["id"])
    return _out(record)


@router.get("/uploads/{upload_id}", response_model=FacebookUploadOut)
def get_upload(upload_id: str) -> FacebookUploadOut:
    record = facebook_upload_store.get(upload_id)
    if not record:
        raise HTTPException(404, "Facebook upload was not found.")
    return _out(record)
