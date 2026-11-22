"""Stage 6 generation and editing APIs for one completed export at a time."""
from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, HTTPException, Response, status

from app.core.config import settings
from app.models.schemas import SocialContentGenerationOut, SocialContentStart, SocialPackageUpdate
from app.services import social_content_store as store
from app.services.project_store import utc_now
from app.services.render_store import get as get_render
from app.services.social_content_queue import enqueue
from app.services.social_content_service import PLATFORMS, PROMPT_VERSION, build_context, public_generation, validate_edit
from app.services.storage import StoragePathError, managed_path

logger = logging.getLogger(__name__)
router = APIRouter(tags=["social content"])


def _out(record: dict) -> SocialContentGenerationOut:
    return SocialContentGenerationOut(**public_generation(record))


def _require_export(render_job_id: str) -> dict:
    job = get_render(render_job_id)
    if not job or job["kind"] != "export":
        raise HTTPException(404, "Export version not found.")
    if job["status"] != "completed" or not job.get("output_relative_path"):
        raise HTTPException(409, "Social content is available only after this export has completed.")
    try:
        path = managed_path(job["output_relative_path"], must_exist=True)
    except (FileNotFoundError, StoragePathError, OSError, ValueError) as exc:
        logger.warning("Completed export path unavailable for social generation %s", render_job_id)
        raise HTTPException(410, "The completed export is missing from managed storage.") from exc
    if not path.is_file() or path.suffix.lower() != ".mp4":
        raise HTTPException(410, "The completed MP4 is missing from managed storage.")
    if path.stat().st_size <= 0:
        raise HTTPException(410, "The completed MP4 is empty.")
    if path.stat().st_size > settings.gemini_file_max_bytes:
        max_gib = settings.gemini_file_max_bytes / 1024**3
        raise HTTPException(413, f"This export exceeds the configured Gemini upload ceiling of {max_gib:.2f} GiB. The video was not changed or uploaded.")
    return job


@router.post("/api/render-jobs/{render_job_id}/social-content-generations", response_model=SocialContentGenerationOut, status_code=status.HTTP_202_ACCEPTED)
def post_generation(render_job_id: str, payload: SocialContentStart, response: Response) -> SocialContentGenerationOut:
    if not payload.consent_to_upload_video:
        raise HTTPException(400, "Explicit consent is required before uploading this export to Google Gemini.")
    if not settings.gemini_api_key:
        raise HTTPException(503, "Gemini is not configured. Set GEMINI_API_KEY in backend/.env to generate social content.")
    job = _require_export(render_job_id)
    try:
        context = build_context(job)
        generation_id = store.create(
            render_job_id=render_job_id,
            model_name=settings.gemini_model,
            prompt_version=PROMPT_VERSION,
            consent_at=utc_now(),
            context=context,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "A social content request is already queued or running for this export. Wait for it to finish before starting another.") from exc
    enqueue(generation_id)
    return _out(store.get(generation_id))


@router.get("/api/render-jobs/{render_job_id}/social-content-generations", response_model=list[SocialContentGenerationOut])
def generation_history(render_job_id: str) -> list[SocialContentGenerationOut]:
    _require_export(render_job_id)
    return [_out(item) for item in store.list_for_export(render_job_id)]


@router.get("/api/social-content-generations/{generation_id}", response_model=SocialContentGenerationOut)
def generation_status(generation_id: str) -> SocialContentGenerationOut:
    record = store.get(generation_id)
    if not record:
        raise HTTPException(404, "Social content generation not found.")
    return _out(record)


@router.patch("/api/social-content-generations/{generation_id}/platforms/{platform}", response_model=SocialContentGenerationOut)
def update_package(generation_id: str, platform: str, payload: SocialPackageUpdate) -> SocialContentGenerationOut:
    if platform not in PLATFORMS:
        raise HTTPException(404, "Unknown social platform.")
    record = store.get(generation_id)
    if not record:
        raise HTTPException(404, "Social content generation not found.")
    try:
        content = validate_edit(platform, payload.content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    updated = store.save_package(generation_id, platform, content)
    if not updated:
        raise HTTPException(409, "Packages can be edited only after generation completes.")
    return _out(updated)
