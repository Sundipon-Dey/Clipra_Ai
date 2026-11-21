"""Explicit clip export requests, version history, and playback."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Response
from fastapi.responses import FileResponse

from app.models.schemas import RenderApproval, RenderJobOut
from app.services.clip_store import get_clip
from app.services.project_store import get_media_record, utc_now
from app.services.range_stream import byte_range, stream_file
from app.services.render_queue import enqueue
from app.services.render_snapshot import capture
from app.services.render_store import create_export, digest, get, list_for_clip
from app.services.storage import StoragePathError, managed_path

logger = logging.getLogger(__name__)
router = APIRouter(tags=["clip exports"])


def _out(job: dict, current_hash: str | None = None) -> RenderJobOut:
    is_current = bool(current_hash and job["config_hash"] == current_hash and job["status"] == "completed")
    snapshot = json.loads(job["snapshot_json"])
    resolution = str(snapshot.get("profile", {}).get("resolution", "1080"))
    return RenderJobOut(**{key: job[key] for key in ("id", "clip_id", "project_id", "kind", "status", "config_hash", "progress", "stage", "error_message", "output_bytes", "version_number", "approved_at", "created_at", "completed_at")},
                        stream_url=f"/api/render-jobs/{job['id']}/stream" if job.get("output_relative_path") else None,
                        download_url=f"/api/render-jobs/{job['id']}/download" if job.get("output_relative_path") and job["kind"] == "export" else None,
                        current=is_current, resolution=resolution if resolution in {"1080", "1440"} else "1080")


@router.post("/api/clips/{clip_id}/exports", response_model=RenderJobOut, status_code=202)
def post_export(clip_id: str, payload: RenderApproval):
    if not payload.approved:
        raise HTTPException(400, "Explicit approval is required before export.")
    clip = get_clip(clip_id)
    if payload.resolution == "1440" and clip:
        media = get_media_record(clip["media_id"])
        if not media or min(int(media["width"]), int(media["height"])) < 1440:
            raise HTTPException(422, "1440p export is available only when the original upload is 1440p or higher.")
    snapshot = capture(clip_id, payload.caption_track_id, payload.resolution)
    if not snapshot:
        if payload.caption_track_id and get_clip(clip_id):
            raise HTTPException(409, "The selected caption track is stale or unavailable. Refresh it before rendering.")
        if get_clip(clip_id):
            raise HTTPException(409, "The split-screen layout needs a valid managed custom image before rendering.")
        raise HTTPException(404, "Draft clip not found.")
    job = create_export(clip_id=clip_id, project_id=snapshot["clip"]["project_id"], snapshot=snapshot, approved_at=utc_now())
    enqueue(job["id"])
    return _out(get(job["id"]) or job)


@router.get("/api/clips/{clip_id}/render-jobs", response_model=list[RenderJobOut])
def render_history(clip_id: str, caption_track_id: str | None = None):
    if not get_clip(clip_id):
        raise HTTPException(404, "Draft clip not found.")
    jobs = list_for_clip(clip_id)
    result = []
    for job in jobs:
        saved = json.loads(job["snapshot_json"])
        profile = str(saved.get("profile", {}).get("resolution", "1080"))
        current = capture(clip_id, caption_track_id, profile)
        result.append(_out(job, digest(current) if current else None))
    return result


@router.get("/api/render-jobs/{job_id}", response_model=RenderJobOut)
def render_status(job_id: str, caption_track_id: str | None = None):
    job = get(job_id)
    if not job or job["kind"] != "export":
        raise HTTPException(404, "Render job not found.")
    if caption_track_id is None:
        saved_track = json.loads(job["snapshot_json"]).get("caption_track")
        caption_track_id = saved_track.get("id") if saved_track else None
    saved = json.loads(job["snapshot_json"])
    profile = str(saved.get("profile", {}).get("resolution", "1080"))
    snapshot = capture(job["clip_id"], caption_track_id, profile)
    return _out(job, digest(snapshot) if snapshot else None)


def _path(job_id: str) -> tuple[dict, Path]:
    job = get(job_id)
    if not job or job["kind"] != "export":
        raise HTTPException(404, "Render job not found.")
    if job["status"] != "completed" or not job["output_relative_path"]:
        raise HTTPException(409, "This render has not completed.")
    try:
        path = managed_path(job["output_relative_path"], must_exist=True)
    except (FileNotFoundError, StoragePathError, OSError, ValueError) as exc:
        logger.error("Rejected missing or unsafe render path for job %s", job_id)
        raise HTTPException(410, "The rendered video is missing from managed storage.") from exc
    if not path.is_file():
        raise HTTPException(410, "The rendered video is missing from managed storage.")
    return job, path


@router.get("/api/render-jobs/{job_id}/stream")
def render_stream(job_id: str, range_header: str | None = Header(default=None, alias="Range")):
    _, path = _path(job_id)
    return stream_file(path, media_type="video/mp4", range_header=range_header)


@router.head("/api/render-jobs/{job_id}/stream")
def render_head(job_id: str, range_header: str | None = Header(default=None, alias="Range")):
    _, path = _path(job_id)
    size = path.stat().st_size
    start, end, partial = byte_range(range_header, size)
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(end-start+1), "Content-Type": "video/mp4", "Cache-Control": "no-store"}
    if partial: headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return Response(status_code=206 if partial else 200, headers=headers)


@router.get("/api/render-jobs/{job_id}/download")
def render_download(job_id: str):
    job, path = _path(job_id)
    return FileResponse(path, media_type="video/mp4", filename=f"clip-v{int(job['version_number'])}.mp4")

