"""Persistence helpers for editable, unapproved clip drafts."""

from __future__ import annotations

import json
from uuid import uuid4

from app.db.database import connect
from app.models.schemas import SplitLayoutConfig
from app.services.project_store import utc_now


def _clip(row, focal_rows) -> dict:
    result = dict(row)
    result["split_layout"] = SplitLayoutConfig.model_validate(json.loads(result.pop("split_layout_json", "{}") or "{}" )).model_dump()
    result["focal_points"] = [dict(point) for point in focal_rows]
    return result


def get_clip(clip_id: str):
    with connect() as db:
        row = db.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        if row is None:
            return None
        points = db.execute("SELECT time_seconds,x,y,confidence FROM clip_focal_points WHERE clip_id=? ORDER BY ordinal", (clip_id,)).fetchall()
    return _clip(row, points)


def list_clips(media_id: str):
    with connect() as db:
        rows = db.execute("SELECT * FROM clips WHERE media_id=? ORDER BY created_at DESC", (media_id,)).fetchall()
        points = {row["id"]: db.execute("SELECT time_seconds,x,y,confidence FROM clip_focal_points WHERE clip_id=? ORDER BY ordinal", (row["id"],)).fetchall() for row in rows}
    return [_clip(row, points[row["id"]]) for row in rows]


def create_clip(*, project_id: str, media_id: str, title: str, start: float, end: float):
    clip_id, now = str(uuid4()), utc_now()
    with connect() as db:
        db.execute("INSERT INTO clips(id,project_id,media_id,source_candidate_id,title,start_seconds,end_seconds,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (clip_id, project_id, media_id, None, title.strip(), start, end, now, now))
    return get_clip(clip_id)


def update_clip(clip_id: str, fields: dict):
    allowed = {"title", "start_seconds", "end_seconds", "framing_mode", "manual_focus_x", "manual_focus_y", "manual_zoom", "blur_strength", "fit_background_color", "manual_override_enabled", "layout_type", "split_layout"}
    values = []
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        if key == "split_layout":
            values.append(("split_layout_json", json.dumps(value, sort_keys=True, separators=(",", ":"))))
        else:
            values.append((key, value))
    if values:
        values.append(("updated_at", utc_now()))
        with connect() as db:
            db.execute(f"UPDATE clips SET {', '.join(f'{key}=?' for key, _ in values)} WHERE id=?", [value for _, value in values] + [clip_id])
    return get_clip(clip_id)


def delete_clip(clip_id: str) -> bool:
    with connect() as db:
        return db.execute("DELETE FROM clips WHERE id=?", (clip_id,)).rowcount == 1


def claim_framing(clip_id: str, *, retry: bool) -> tuple[bool, dict | None]:
    """Atomic idempotent state transition. Only one caller schedules external work."""
    scheduled = False
    with connect() as db:
        row = db.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        if row is None:
            return False, None
        can_start = row["framing_status"] != "pending" and (retry or row["framing_status"] == "not_requested")
        if can_start:
            now = utc_now()
            changed = db.execute("UPDATE clips SET framing_status='pending',framing_error_code=NULL,framing_error_message=NULL,framing_requested_at=?,framing_completed_at=NULL,framing_start_seconds=start_seconds,framing_end_seconds=end_seconds,updated_at=? WHERE id=? AND framing_status != 'pending'", (now, now, clip_id)).rowcount
            scheduled = changed == 1
    return scheduled, get_clip(clip_id)


def complete_framing(clip_id: str, *, model: str, points: list[dict]):
    now = utc_now()
    with connect() as db:
        db.execute("DELETE FROM clip_focal_points WHERE clip_id=?", (clip_id,))
        db.executemany("INSERT INTO clip_focal_points(id,clip_id,ordinal,time_seconds,x,y,confidence) VALUES(?,?,?,?,?,?,?)",
                       [(str(uuid4()), clip_id, i, p["time_seconds"], p["x"], p["y"], p.get("confidence")) for i, p in enumerate(points)])
        db.execute("UPDATE clips SET framing_status='completed',framing_error_code=NULL,framing_error_message=NULL,framing_model=?,framing_completed_at=?,recommended_framing_mode='smart_crop',framing_start_seconds=start_seconds,framing_end_seconds=end_seconds,updated_at=? WHERE id=?",
                   (model, now, now, clip_id))
    return get_clip(clip_id)


def fail_framing(clip_id: str, *, code: str, message: str):
    with connect() as db:
        db.execute("UPDATE clips SET framing_status='failed',framing_error_code=?,framing_error_message=?,framing_completed_at=?,updated_at=? WHERE id=?",
                   (code, message, utc_now(), utc_now(), clip_id))
    return get_clip(clip_id)
