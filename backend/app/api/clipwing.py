"""Project-scoped imports for pasted Clipwing suggestions."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.models.schemas import ClipwingDownloadRequest, ClipwingImportOut, ClipwingImportRequest
from app.services.clipwing_imports import create_import, get_entry, get_import, list_imports, parse_clipwing_text, set_entry, set_job
from app.services.clipwing_queue import enqueue_download, enqueue_lookup, invalidate_metadata
from app.services.project_store import project_exists

router = APIRouter(prefix="/api/projects/{project_id}/clipwing-imports", tags=["Clipwing imports"])


def _out(record: dict) -> ClipwingImportOut:
    return ClipwingImportOut(**record)


@router.post("", response_model=ClipwingImportOut, status_code=status.HTTP_202_ACCEPTED)
def start_clipwing_import(project_id: str, payload: ClipwingImportRequest) -> ClipwingImportOut:
    if not project_exists(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    if not payload.confirm_rights:
        raise HTTPException(status_code=400, detail="Confirm that you have permission to download and edit this video.")
    try:
        video_url, entries = parse_clipwing_text(payload.analysis_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    import_id = create_import(project_id=project_id, analysis_text=payload.analysis_text, video_url=video_url, entries=entries)
    enqueue_lookup(import_id)
    record = get_import(import_id)
    return _out(record)


@router.get("", response_model=list[ClipwingImportOut])
def clipwing_import_history(project_id: str) -> list[ClipwingImportOut]:
    if not project_exists(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    return [_out(record) for record in list_imports(project_id)]


@router.get("/{import_id}", response_model=ClipwingImportOut)
def get_clipwing_import(project_id: str, import_id: str) -> ClipwingImportOut:
    record = get_import(import_id)
    if not record or record["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Clipwing import not found.")
    return _out(record)


@router.post("/{import_id}/refresh", response_model=ClipwingImportOut, status_code=status.HTTP_202_ACCEPTED)
def refresh_clipwing_details(project_id: str, import_id: str) -> ClipwingImportOut:
    record = get_import(import_id)
    if not record or record["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Clipwing import not found.")
    if any(entry["status"] == "cutting" for entry in record["entries"]):
        raise HTTPException(status_code=409, detail="Wait for the current clip download to finish before refreshing video details.")
    invalidate_metadata(import_id)
    for entry in record["entries"]:
        if entry["status"] in {"failed", "interrupted"} and not entry["media_id"]:
            set_entry(entry["id"], status="queued", progress=0, error_message=None)
    set_job(import_id, status="queued", stage="Refreshing available video formats", progress=0)
    enqueue_lookup(import_id)
    return _out(get_import(import_id))


@router.post("/{import_id}/entries/{entry_id}/download", response_model=ClipwingImportOut, status_code=status.HTTP_202_ACCEPTED)
def download_clipwing_entry(project_id: str, import_id: str, entry_id: str, payload: ClipwingDownloadRequest) -> ClipwingImportOut:
    record = get_import(import_id)
    if not record or record["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Clipwing import not found.")
    if record["status"] != "completed" or not record["formats"]:
        raise HTTPException(status_code=409, detail="Video format details are not ready. Refresh the video details before downloading a clip.")
    entry = get_entry(entry_id)
    if not entry or entry["import_id"] != import_id:
        raise HTTPException(status_code=404, detail="Clipwing suggestion not found.")
    if not any(item["format_id"] == payload.format_id for item in record["formats"]):
        raise HTTPException(status_code=422, detail="That format is no longer available. Refresh the video details and choose another format.")
    if entry["status"] == "cutting":
        raise HTTPException(status_code=409, detail="This clip is already queued or downloading.")
    if entry["status"] == "ready":
        raise HTTPException(status_code=409, detail="This clip has already been downloaded.")
    set_entry(entry_id, status="cutting", progress=0, selected_format_id=payload.format_id)
    enqueue_download(import_id, entry_id, payload.format_id)
    return _out(get_import(import_id))
