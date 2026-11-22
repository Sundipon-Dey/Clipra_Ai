"""Draft clip editing and optional Smart Crop recommendation endpoints."""

from fastapi import APIRouter, HTTPException, Response, status

from app.core.config import settings
from app.models.schemas import ClipCreate, ClipOut, ClipUpdate, FramingSuggestionRequest
from app.services.clip_store import claim_framing, create_clip, delete_clip, get_clip, list_clips, update_clip
from app.services.framing_queue import enqueue_framing
from app.services.project_store import get_media_record
from app.services.caption_store import mark_tracks_stale
from app.services.layout_image_store import get_layout_image

router = APIRouter(tags=["draft clips"])
FRAMING_MODES = {"smart_crop", "fit", "blurred_background", "manual_crop"}


def _duration(media_id: str):
    media = get_media_record(media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Imported video not found.")
    return media


def _validate_bounds(start: float, end: float, duration: float):
    if start < 0 or end <= start or end > duration:
        raise HTTPException(status_code=422, detail=f"Clip boundaries must satisfy 0 ≤ start < end ≤ source duration ({duration:.3f} seconds).")


@router.get("/api/media/{media_id}/clips", response_model=list[ClipOut])
def get_media_clips(media_id: str):
    _duration(media_id)
    return list_clips(media_id)


@router.post("/api/media/{media_id}/clips", response_model=ClipOut, status_code=status.HTTP_201_CREATED)
def post_manual_clip(media_id: str, payload: ClipCreate):
    media = _duration(media_id)
    _validate_bounds(payload.start_seconds, payload.end_seconds, media["duration_seconds"])
    return create_clip(project_id=media["project_id"], media_id=media_id, title=payload.title, start=payload.start_seconds, end=payload.end_seconds)


@router.get("/api/clips/{clip_id}", response_model=ClipOut)
def get_one_clip(clip_id: str):
    clip = get_clip(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Draft clip not found.")
    return clip


@router.patch("/api/clips/{clip_id}", response_model=ClipOut)
def patch_clip(clip_id: str, payload: ClipUpdate):
    clip = get_clip(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Draft clip not found.")
    fields = payload.model_dump(exclude_unset=True, exclude_none=True)
    if fields.get("framing_mode") is not None and fields["framing_mode"] not in FRAMING_MODES:
        raise HTTPException(status_code=422, detail="Choose Smart Crop, Fit / Original, Blurred Background, or Manual Crop.")
    split_layout = fields.get("split_layout")
    if split_layout:
        for section in (split_layout["top"], split_layout["bottom"]):
            image_id = section.get("image_asset_id")
            if section.get("source_mode") == "custom_image" and (not image_id or not get_layout_image(image_id, clip_id)):
                raise HTTPException(status_code=422, detail="A selected custom image does not belong to this clip.")
    start = fields.get("start_seconds", clip["start_seconds"])
    end = fields.get("end_seconds", clip["end_seconds"])
    media = _duration(clip["media_id"])
    _validate_bounds(start, end, media["duration_seconds"])
    if end - start < 0.04:
        raise HTTPException(status_code=422, detail="A clip must be at least 0.04 seconds long.")
    updated = update_clip(clip_id, fields)
    mark_tracks_stale(clip_id, updated["start_seconds"], updated["end_seconds"])
    return updated


@router.delete("/api/clips/{clip_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft_clip(clip_id: str):
    if not delete_clip(clip_id):
        raise HTTPException(status_code=404, detail="Draft clip not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/clips/{clip_id}/framing-suggestion", response_model=ClipOut)
def request_framing(clip_id: str, payload: FramingSuggestionRequest, response: Response):
    clip = get_clip(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Draft clip not found.")
    if not payload.consent_to_send_frames:
        raise HTTPException(status_code=400, detail="Explicit consent is required before selected frames are sent to Google.")
    if not settings.gemini_api_key:
        raise HTTPException(status_code=503, detail="Gemini is not configured. Manual framing remains available.")
    media = _duration(clip["media_id"])
    _validate_bounds(clip["start_seconds"], clip["end_seconds"], media["duration_seconds"])
    scheduled, current = claim_framing(clip_id, retry=payload.retry)
    if current is None:
        raise HTTPException(status_code=404, detail="Draft clip not found.")
    if scheduled:
        response.status_code = status.HTTP_202_ACCEPTED
        enqueue_framing(clip_id)
        return get_clip(clip_id) or current
    response.status_code = status.HTTP_200_OK
    return current
