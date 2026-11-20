"""Local transcription, caption track, and render-compatible styling APIs."""

import json
import sqlite3

from fastapi import APIRouter, HTTPException, Response, status

from app.models.schemas import (CaptionReflow, CaptionSegmentUpdate, CaptionTrackCreate, CaptionTrackOut, CaptionTrackUpdate, CaptionWordUpdate, HardwareProfileOut, ModelDownloadOut, TranscriptionModelOut, TranscriptionRunOut, TranscriptionStart)
from app.services.caption_grouping import normalize_grouping
from app.services.caption_store import (clear_transcriptions, create_empty_track, create_run, get_run, get_track, list_runs, list_tracks, reflow_track, update_segment, update_track, update_word)
from app.services.caption_styles import ALLOWED_SAFE_ZONES, PRESETS, preset_style, validate_style
from app.services.clip_store import get_clip
from app.services.project_store import get_media_record
from app.services.hardware_profile import hardware_profile
from app.services.transcription_models import begin_download, download_status, installed, list_models
from app.services.transcription_queue import enqueue_transcription

router = APIRouter(tags=["local captions"])


def _track_out(track: dict) -> CaptionTrackOut:
    return CaptionTrackOut(**track)


def _run_out(run: dict) -> TranscriptionRunOut:
    return TranscriptionRunOut(**run)


@router.get("/api/transcription/hardware-profile", response_model=HardwareProfileOut)
def get_hardware_profile() -> HardwareProfileOut:
    return HardwareProfileOut(**hardware_profile())


@router.get("/api/transcription/models", response_model=list[TranscriptionModelOut])
def get_transcription_models() -> list[TranscriptionModelOut]:
    return [TranscriptionModelOut(**item) for item in list_models(hardware_profile()["recommendation_model"])]


@router.get("/api/transcription/models/{model_id}", response_model=ModelDownloadOut)
def get_model_status(model_id: str) -> ModelDownloadOut:
    try:
        return ModelDownloadOut(**download_status(model_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/transcription/models/{model_id}/download", response_model=ModelDownloadOut, status_code=status.HTTP_202_ACCEPTED)
def post_model_download(model_id: str) -> ModelDownloadOut:
    try:
        return ModelDownloadOut(**begin_download(model_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/clips/{clip_id}/transcriptions", response_model=TranscriptionRunOut, status_code=status.HTTP_202_ACCEPTED)
def post_transcription(clip_id: str, payload: TranscriptionStart, response: Response) -> TranscriptionRunOut:
    clip = get_clip(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Draft clip not found.")
    profile = hardware_profile()
    model_id = payload.model_id or profile["recommendation_model"]
    if model_id not in {item["id"] for item in list_models(profile["recommendation_model"])}:
        raise HTTPException(status_code=422, detail="Unsupported transcription model.")
    if not installed(model_id):
        raise HTTPException(status_code=409, detail="This model is not installed. Select Download model to explicitly download it before transcription.")
    if payload.language != "en":
        raise HTTPException(status_code=422, detail="Stage 4 currently supports English transcription only.")
    device_profile = "cpu:int8"
    try:
        start = payload.start_seconds if payload.start_seconds is not None else clip["start_seconds"]
        end = payload.end_seconds if payload.end_seconds is not None else clip["end_seconds"]
        media = get_media_record(clip["media_id"])
        if end <= start or end > media["duration_seconds"]:
            raise HTTPException(status_code=422, detail="Transcription boundaries must fit within the source video and end after start.")
        run_id = create_run(clip=clip, model_id=model_id, language=payload.language, device_profile=device_profile, start=start, end=end)
    except sqlite3.IntegrityError:
        current = next((run for run in list_runs(clip_id) if run["status"] in {"queued", "extracting", "transcribing"}), None)
        if current:
            response.status_code = status.HTTP_200_OK
            return _run_out(current)
        raise
    enqueue_transcription(run_id)
    return _run_out(get_run(run_id))


@router.get("/api/clips/{clip_id}/transcriptions", response_model=list[TranscriptionRunOut])
def get_clip_transcriptions(clip_id: str) -> list[TranscriptionRunOut]:
    if get_clip(clip_id) is None:
        raise HTTPException(status_code=404, detail="Draft clip not found.")
    return [_run_out(run) for run in list_runs(clip_id)]


@router.delete("/api/clips/{clip_id}/transcriptions", status_code=status.HTTP_204_NO_CONTENT)
def delete_clip_transcriptions(clip_id: str):
    if get_clip(clip_id) is None:
        raise HTTPException(status_code=404, detail="Draft clip not found.")
    clear_transcriptions(clip_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/transcriptions/{run_id}", response_model=TranscriptionRunOut)
def get_transcription(run_id: str) -> TranscriptionRunOut:
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Transcription run not found.")
    return _run_out(run)


@router.get("/api/clips/{clip_id}/caption-tracks", response_model=list[CaptionTrackOut])
def get_caption_tracks(clip_id: str) -> list[CaptionTrackOut]:
    if get_clip(clip_id) is None:
        raise HTTPException(status_code=404, detail="Draft clip not found.")
    return [_track_out(track) for track in list_tracks(clip_id)]


@router.post("/api/clips/{clip_id}/caption-tracks", response_model=CaptionTrackOut, status_code=status.HTTP_201_CREATED)
def post_caption_track(clip_id: str, payload: CaptionTrackCreate) -> CaptionTrackOut:
    clip = get_clip(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Draft clip not found.")
    if payload.preset_id not in PRESETS:
        raise HTTPException(status_code=422, detail="Unknown caption preset.")
    if payload.transcription_run_id:
        run = get_run(payload.transcription_run_id)
        if run is None or run["clip_id"] != clip_id:
            raise HTTPException(status_code=422, detail="The selected transcription does not belong to this clip.")
        if run["caption_track_id"]:
            track = get_track(run["caption_track_id"])
            return _track_out(track)
        raise HTTPException(status_code=409, detail="This transcription has not completed caption generation.")
    return _track_out(create_empty_track(clip=clip, name=payload.name, preset_id=payload.preset_id))


@router.get("/api/caption-tracks/{track_id}", response_model=CaptionTrackOut)
def get_caption_track(track_id: str) -> CaptionTrackOut:
    track = get_track(track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="Caption track not found.")
    return _track_out(track)


@router.patch("/api/caption-tracks/{track_id}", response_model=CaptionTrackOut)
def patch_caption_track(track_id: str, payload: CaptionTrackUpdate) -> CaptionTrackOut:
    track = get_track(track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="Caption track not found.")
    fields = payload.model_dump(exclude_unset=True, exclude_none=True)
    try:
        if "preset_id" in fields:
            fields["style_json"] = json.dumps(preset_style(fields["preset_id"]))
        if "style" in fields:
            fields["style_json"] = json.dumps(validate_style(fields.pop("style")))
        if "grouping" in fields:
            fields["grouping_json"] = json.dumps(normalize_grouping(fields.pop("grouping")))
        if fields.get("safe_zone_profile") not in {None, *ALLOWED_SAFE_ZONES}:
            raise ValueError("Unknown safe-zone profile.")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    updated = update_track(track_id, fields)
    return _track_out(updated)


@router.post("/api/caption-tracks/{track_id}/reflow", response_model=CaptionTrackOut)
def post_reflow(track_id: str, payload: CaptionReflow) -> CaptionTrackOut:
    track = get_track(track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="Caption track not found.")
    try:
        updated = reflow_track(track_id, {**track["grouping"], **payload.model_dump()})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _track_out(updated)


@router.patch("/api/caption-segments/{segment_id}", response_model=CaptionTrackOut)
def patch_caption_segment(segment_id: str, payload: CaptionSegmentUpdate) -> CaptionTrackOut:
    fields = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "start_seconds" in fields and "end_seconds" in fields and fields["end_seconds"] <= fields["start_seconds"]:
        raise HTTPException(status_code=422, detail="Caption segment end must be after its start.")
    track = update_segment(segment_id, fields)
    if track is None:
        raise HTTPException(status_code=404, detail="Caption segment not found.")
    return _track_out(track)


@router.patch("/api/caption-words/{word_id}", response_model=CaptionTrackOut)
def patch_caption_word(word_id: str, payload: CaptionWordUpdate) -> CaptionTrackOut:
    track = update_word(word_id, payload.text)
    if track is None:
        raise HTTPException(status_code=404, detail="Caption word not found.")
    return _track_out(track)
