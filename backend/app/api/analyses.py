"""Explicitly requested Gemini analysis jobs and persisted review results."""

import sqlite3

from fastapi import APIRouter, HTTPException, Response, status

from app.core.config import settings
from app.models.schemas import AnalysisRunOut, AnalysisStart
from app.services.analysis_queue import enqueue_analysis
from app.services.highlight_analysis import ACTIVE_STATUSES, PROMPT_VERSION
from app.services.project_store import (
    analysis_candidates,
    create_analysis_run,
    get_analysis_run_record,
    get_latest_analysis_record,
    get_media_record,
    list_analysis_records,
)


router = APIRouter(tags=["Gemini analysis"])


def _out(row) -> AnalysisRunOut:
    return AnalysisRunOut(
        id=row["id"],
        project_id=row["project_id"],
        media_id=row["media_id"],
        status=row["status"],
        model_name=row["model_name"],
        prompt_version=row["prompt_version"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        cleanup_pending=bool(row["cleanup_pending"]),
        candidates=[dict(candidate) for candidate in analysis_candidates(row["id"])],
    )


@router.post("/api/media/{media_id}/analyses", response_model=AnalysisRunOut)
def start_analysis(media_id: str, payload: AnalysisStart, response: Response) -> AnalysisRunOut:
    media = get_media_record(media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Imported video not found.")
    if not settings.gemini_api_key:
        raise HTTPException(status_code=503, detail="Gemini is not configured. Add GEMINI_API_KEY to backend/.env and restart the backend.")

    latest = get_latest_analysis_record(media_id)
    if latest is not None:
        if latest["status"] in ACTIVE_STATUSES:
            return _out(latest)
        if not payload.force:
            return _out(latest)

    try:
        run_id = create_analysis_run(
            project_id=media["project_id"],
            media_id=media_id,
            source_size_bytes=media["size_bytes"],
            model_name=settings.gemini_model,
            prompt_version=PROMPT_VERSION,
        )
    except sqlite3.IntegrityError:
        # The partial unique index closes the race between simultaneous start requests.
        current = get_latest_analysis_record(media_id)
        if current is None or current["status"] not in ACTIVE_STATUSES:
            raise
        return _out(current)
    response.status_code = status.HTTP_202_ACCEPTED
    enqueue_analysis(run_id)
    row = get_analysis_run_record(run_id)
    return _out(row)


@router.get("/api/media/{media_id}/analyses", response_model=list[AnalysisRunOut])
def get_analysis_history(media_id: str) -> list[AnalysisRunOut]:
    if get_media_record(media_id) is None:
        raise HTTPException(status_code=404, detail="Imported video not found.")
    return [_out(row) for row in list_analysis_records(media_id)]


@router.get("/api/analyses/{analysis_id}", response_model=AnalysisRunOut)
def get_analysis(analysis_id: str) -> AnalysisRunOut:
    row = get_analysis_run_record(analysis_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Analysis run not found.")
    return _out(row)
