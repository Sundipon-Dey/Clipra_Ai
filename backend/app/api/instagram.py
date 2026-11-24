"""Instagram professional-account authorization and Reels publishing endpoints."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, status

from app.models.schemas import InstagramStatusOut, InstagramUploadOut, InstagramUploadStart
from app.services import facebook_auth, instagram_auth, instagram_r2_storage, instagram_upload_store, social_content_store
from app.services.facebook_auth import FacebookAuthError
from app.services.instagram_upload_queue import enqueue
from app.services.render_store import get as get_render
from app.services.storage import StoragePathError, managed_path

router = APIRouter(prefix="/api/social/instagram", tags=["Instagram publishing"])


def _export_path(render_job_id: str):
    job = get_render(render_job_id)
    if not job or job.get("kind") != "export":
        raise HTTPException(404, "Export version not found.")
    if job.get("status") != "completed" or not job.get("output_relative_path"):
        raise HTTPException(409, "Only a completed export can be published to Instagram.")
    try:
        path = managed_path(job["output_relative_path"], must_exist=True)
    except (FileNotFoundError, StoragePathError, OSError, ValueError) as exc:
        raise HTTPException(410, "The completed export is missing from managed storage.") from exc
    if not path.is_file() or path.suffix.lower() != ".mp4" or path.stat().st_size <= 0:
        raise HTTPException(410, "The completed MP4 is missing or empty.")
    return path


def _out(record: dict) -> InstagramUploadOut:
    return InstagramUploadOut(**record)


@router.get("/status", response_model=InstagramStatusOut)
def get_status() -> InstagramStatusOut:
    return InstagramStatusOut(**instagram_auth.status())


@router.post("/connect", status_code=status.HTTP_202_ACCEPTED)
def connect_account() -> dict[str, str]:
    try:
        message = facebook_auth.begin_connect(include_instagram=True)
    except FacebookAuthError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"status": "authorization_started", "message": message}


@router.get("/exports/{render_job_id}/uploads", response_model=list[InstagramUploadOut])
def list_uploads(render_job_id: str) -> list[InstagramUploadOut]:
    _export_path(render_job_id)
    return [_out(record) for record in instagram_upload_store.list_for_render(render_job_id)]


@router.post("/exports/{render_job_id}/uploads", response_model=InstagramUploadOut, status_code=status.HTTP_202_ACCEPTED)
def start_upload(render_job_id: str, payload: InstagramUploadStart) -> InstagramUploadOut:
    if not payload.approved:
        raise HTTPException(400, "Explicitly approve this Instagram Reel before publishing.")
    if not instagram_r2_storage.configured():
        raise HTTPException(409, "Configure all four Cloudflare R2 values in backend/.env before publishing Instagram Reels.")
    path = _export_path(render_job_id)
    account = instagram_auth.selected_account(payload.instagram_user_id)
    if not account:
        raise HTTPException(409, "Connect Meta and choose a linked Instagram professional account before publishing.")
    generation = social_content_store.get(payload.generation_id)
    if not generation or generation.get("render_job_id") != render_job_id or generation.get("status") != "completed":
        raise HTTPException(409, "Generate and review Instagram Reels content for this exact export before publishing.")
    packages = dict(generation.get("generated_packages") or {})
    packages.update(generation.get("edited_packages") or {})
    package = packages.get("instagram_reels")
    if not isinstance(package, dict):
        raise HTTPException(409, "The saved Instagram Reels package is unavailable. Generate or save it before publishing.")
    try:
        record = instagram_upload_store.create(
            render_job_id=render_job_id,
            generation_id=payload.generation_id,
            account=account,
        )
    except (RuntimeError, sqlite3.IntegrityError) as exc:
        raise HTTPException(409, str(exc)) from exc
    enqueue(record["id"], path, package, payload.instagram_user_id)
    return _out(record)


@router.get("/uploads/{upload_id}", response_model=InstagramUploadOut)
def get_upload(upload_id: str) -> InstagramUploadOut:
    record = instagram_upload_store.get(upload_id)
    if not record:
        raise HTTPException(404, "Instagram upload was not found.")
    return _out(record)
