"""Project and multi-file media import routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile, status, Response

from app.core.config import settings
from app.models.schemas import ImportFailure, ImportResult, ProjectCreate, ProjectDetail, ProjectSummary
from app.services.media_validation import MediaToolError, MediaValidationError
from app.services.project_store import create_project, delete_project, get_project, list_projects, project_exists
from app.services.storage import display_filename, import_upload


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["projects", "media"])


@router.post("/projects", response_model=ProjectSummary, status_code=status.HTTP_201_CREATED)
def post_project(payload: ProjectCreate) -> ProjectSummary:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Project name cannot be blank.")
    return create_project(name)


@router.get("/projects", response_model=list[ProjectSummary])
def get_projects() -> list[ProjectSummary]:
    return list_projects()


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project(project_id: str):
    if not delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def get_project_detail(project_id: str) -> ProjectDetail:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


@router.post("/projects/{project_id}/media", response_model=ImportResult)
def post_project_media(project_id: str, files: list[UploadFile] = File(...)) -> ImportResult:
    if not project_exists(project_id):
        for upload in files:
            upload.file.close()
        raise HTTPException(status_code=404, detail="Project not found.")

    imported = []
    failed: list[ImportFailure] = []
    maximum = settings.max_files_per_import
    for index, upload in enumerate(files):
        filename = display_filename(upload.filename)
        if index >= maximum:
            upload.file.close()
            failed.append(ImportFailure(filename=filename, error=f"A single import is limited to {maximum} files."))
            continue
        try:
            imported.append(import_upload(project_id, upload))
        except (MediaValidationError, MediaToolError, FileNotFoundError, LookupError) as error:
            failed.append(ImportFailure(filename=filename, error=str(error)))
        except Exception:
            logger.exception("Unexpected error importing a local video")
            failed.append(ImportFailure(filename=filename, error="Import failed because of an unexpected local storage error."))
        finally:
            upload.file.close()

    return ImportResult(imported=imported, failed=failed)
