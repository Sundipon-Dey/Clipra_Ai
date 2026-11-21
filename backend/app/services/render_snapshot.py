"""Capture all mutable clip and caption values into a stable render input."""
from __future__ import annotations

from app.services.clip_store import get_clip
from app.services.caption_store import list_tracks
from app.services.project_store import get_media_record
from app.services.layout_image_store import get_layout_image
from app.services.storage import managed_path


def capture(clip_id: str, caption_track_id: str | None = None) -> dict | None:
    clip = get_clip(clip_id)
    if not clip:
        return None
    media = get_media_record(clip["media_id"])
    if not media:
        return None
    clip = dict(clip)
    clip["manual_override_enabled"] = bool(clip.get("manual_override_enabled", 0))
    tracks = list_tracks(clip_id)
    track = next((item for item in tracks if item["id"] == caption_track_id), None) if caption_track_id else next((item for item in tracks if not item["stale"]), None)
    if caption_track_id and track is None:
        return None
    if caption_track_id and track and track["stale"]:
        return None
    # A track is included only when it was authored for the current clip boundaries.
    if track and (abs(track["boundary_start_seconds"] - clip["start_seconds"]) > .001 or abs(track["boundary_end_seconds"] - clip["end_seconds"]) > .001):
        if caption_track_id:
            return None
        track = None
    split_layout = clip["split_layout"]
    layout_image_relative_path = None
    if clip["layout_type"] == "split_streamer_gameplay" and split_layout["top"]["source_mode"] == "custom_image":
        asset_id = split_layout["top"].get("image_asset_id")
        asset = get_layout_image(asset_id, clip_id) if asset_id else None
        if not asset:
            return None
        managed_path(asset["relative_path"], must_exist=True)
        layout_image_relative_path = asset["relative_path"]
    clip_snapshot = dict(clip)
    snapshot = {
        "profile": {"aspect_ratio": "9:16", "width": 1080, "height": 1920},
        "clip": clip_snapshot,
        "source_relative_path": media["source_relative_path"],
        "source_size_bytes": media["size_bytes"],
        "source_duration_seconds": media["duration_seconds"],
        "has_audio": bool(media["has_audio"]),
        "focal_points": clip["focal_points"] if clip["framing_start_seconds"] == clip["start_seconds"] and clip["framing_end_seconds"] == clip["end_seconds"] else [],
        "caption_track": track,
    }
    if clip["layout_type"] == "original":
        # Keep the historical Original Layout snapshot shape stable across migrations.
        clip_snapshot.pop("layout_type", None)
        clip_snapshot.pop("split_layout", None)
    else:
        snapshot["source_frame_rate_decimal"] = media["frame_rate_decimal"] or 30
        snapshot["layout_image_relative_path"] = layout_image_relative_path
    return snapshot

