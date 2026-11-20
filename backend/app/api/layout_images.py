"""Clip-scoped custom images for the split-screen layout."""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.models.schemas import LayoutImageOut
from app.services.clip_store import get_clip
from app.services.layout_image_store import LayoutImageError, get_layout_image, list_layout_images, upload_layout_image
from app.services.storage import StoragePathError, managed_path

logger = logging.getLogger(__name__)
router = APIRouter(tags=["split-screen layout images"])


@router.get("/api/clips/{clip_id}/layout-images", response_model=list[LayoutImageOut])
def get_clip_layout_images(clip_id: str):
    if not get_clip(clip_id):
        raise HTTPException(404, "Draft clip not found.")
    return list_layout_images(clip_id)


@router.post("/api/clips/{clip_id}/layout-images", response_model=LayoutImageOut, status_code=status.HTTP_201_CREATED)
def post_clip_layout_image(clip_id: str, file: UploadFile = File(...)):
    try:
        asset = upload_layout_image(clip_id, file)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except LayoutImageError as exc:
        raise HTTPException(422, str(exc)) from exc
    return asset


@router.get("/api/layout-images/{asset_id}")
def stream_layout_image(asset_id: str):
    asset = get_layout_image(asset_id)
    if not asset:
        raise HTTPException(404, "Layout image not found.")
    try:
        path = managed_path(asset["relative_path"], must_exist=True)
    except (FileNotFoundError, StoragePathError, OSError, ValueError) as exc:
        logger.error("Rejected missing or unsafe layout image path for asset %s", asset_id)
        raise HTTPException(410, "The stored layout image is missing from managed storage.") from exc
    return FileResponse(path, media_type=asset["content_type"], filename=asset["original_filename"])

