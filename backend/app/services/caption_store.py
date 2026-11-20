"""SQLite persistence for local transcription runs and editable caption tracks."""

from __future__ import annotations

import json
from uuid import uuid4

from app.db.database import connect
from app.services.caption_grouping import DEFAULT_GROUPING, group_words, normalize_grouping
from app.services.caption_styles import STYLE_VERSION, preset_style, validate_style
from app.services.project_store import utc_now


def _track(row, segments) -> dict:
    data = dict(row)
    data["style"] = json.loads(data.pop("style_json"))
    data["grouping"] = json.loads(data.pop("grouping_json"))
    data["stale"] = bool(data["stale"])
    data["segments"] = segments
    return data


def _segments(db, track_id: str) -> list[dict]:
    rows = db.execute("SELECT * FROM caption_segments WHERE track_id=? ORDER BY ordinal", (track_id,)).fetchall()
    result = []
    for row in rows:
        segment = dict(row)
        segment["manually_edited"] = bool(segment["manually_edited"])
        segment["words"] = [dict(word) for word in db.execute("SELECT * FROM caption_words WHERE segment_id=? ORDER BY ordinal", (row["id"],)).fetchall()]
        result.append(segment)
    return result


def get_track(track_id: str):
    with connect() as db:
        row = db.execute("SELECT * FROM caption_tracks WHERE id=?", (track_id,)).fetchone()
        return _track(row, _segments(db, track_id)) if row else None


def list_tracks(clip_id: str) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT * FROM caption_tracks WHERE clip_id=? ORDER BY created_at DESC", (clip_id,)).fetchall()
        return [_track(row, _segments(db, row["id"])) for row in rows]


def create_run(*, clip: dict, model_id: str, language: str, device_profile: str, start: float | None = None, end: float | None = None) -> str:
    run_id, now = str(uuid4()), utc_now()
    with connect() as db:
        db.execute("INSERT INTO transcription_runs(id,clip_id,media_id,status,model_id,language,device_profile,clip_start_seconds,clip_end_seconds,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (run_id, clip["id"], clip["media_id"], "queued", model_id, language, device_profile, start if start is not None else clip["start_seconds"], end if end is not None else clip["end_seconds"], now))
    return run_id


def get_run(run_id: str):
    with connect() as db:
        row = db.execute("SELECT r.*, t.id AS caption_track_id FROM transcription_runs r LEFT JOIN caption_tracks t ON t.transcription_run_id=r.id WHERE r.id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_runs(clip_id: str):
    with connect() as db:
        rows = db.execute("SELECT r.*, t.id AS caption_track_id FROM transcription_runs r LEFT JOIN caption_tracks t ON t.transcription_run_id=r.id WHERE r.clip_id=? ORDER BY r.created_at DESC", (clip_id,)).fetchall()
    return [dict(row) for row in rows]


def queued_run_ids() -> list[str]:
    with connect() as db:
        return [row["id"] for row in db.execute("SELECT id FROM transcription_runs WHERE status='queued' ORDER BY created_at").fetchall()]


def update_run(run_id: str, status: str, *, error_code: str | None = None, error_message: str | None = None, started: bool = False, completed: bool = False) -> None:
    fields, values = ["status=?", "error_code=?", "error_message=?"], [status, error_code, error_message]
    if started:
        fields.append("started_at=?"); values.append(utc_now())
    if completed:
        fields.append("completed_at=?"); values.append(utc_now())
    values.append(run_id)
    with connect() as db:
        db.execute(f"UPDATE transcription_runs SET {', '.join(fields)} WHERE id=?", values)


def create_track_from_words(*, run: dict, words: list[dict], preset_id: str = "karaoke_focus") -> dict:
    track_id, now = str(uuid4()), utc_now()
    grouping = normalize_grouping(DEFAULT_GROUPING)
    style = preset_style(preset_id)
    segments = group_words(words, grouping)
    with connect() as db:
        db.execute("INSERT INTO caption_tracks(id,clip_id,transcription_run_id,name,language,preset_id,style_version,style_json,grouping_json,boundary_start_seconds,boundary_end_seconds,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (track_id, run["clip_id"], run["id"], "Generated captions", run["language"], preset_id, STYLE_VERSION, json.dumps(style), json.dumps(grouping), run["clip_start_seconds"], run["clip_end_seconds"], now, now))
        _replace_segments(db, track_id, segments)
    return get_track(track_id)


def create_empty_track(*, clip: dict, name: str, preset_id: str) -> dict:
    style = preset_style(preset_id)
    track_id, now = str(uuid4()), utc_now()
    with connect() as db:
        db.execute("INSERT INTO caption_tracks(id,clip_id,name,language,preset_id,style_version,style_json,grouping_json,boundary_start_seconds,boundary_end_seconds,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (track_id, clip["id"], name.strip(), "en", preset_id, STYLE_VERSION, json.dumps(style), json.dumps(DEFAULT_GROUPING), clip["start_seconds"], clip["end_seconds"], now, now))
    return get_track(track_id)


def _replace_segments(db, track_id: str, segments: list[dict]) -> None:
    db.execute("DELETE FROM caption_segments WHERE track_id=?", (track_id,))
    for ordinal, segment in enumerate(segments):
        segment_id = str(uuid4())
        db.execute("INSERT INTO caption_segments(id,track_id,ordinal,start_seconds,end_seconds,generated_text) VALUES(?,?,?,?,?,?)", (segment_id, track_id, ordinal, segment["start_seconds"], segment["end_seconds"], segment["generated_text"]))
        db.executemany("INSERT INTO caption_words(id,segment_id,ordinal,start_seconds,end_seconds,original_text,text,confidence) VALUES(?,?,?,?,?,?,?,?)", [(str(uuid4()), segment_id, index, word["start_seconds"], word["end_seconds"], word["text"], word["text"], word.get("confidence")) for index, word in enumerate(segment["words"])])


def update_track(track_id: str, fields: dict) -> dict | None:
    allowed = {"name", "preset_id", "style_json", "grouping_json", "position_x", "position_y", "safe_zone_profile", "timing_offset_seconds"}
    pairs = [(key, value) for key, value in fields.items() if key in allowed and value is not None]
    if pairs:
        pairs.append(("updated_at", utc_now()))
        with connect() as db:
            db.execute(f"UPDATE caption_tracks SET {', '.join(f'{key}=?' for key, _ in pairs)} WHERE id=?", [value for _, value in pairs] + [track_id])
    return get_track(track_id)


def update_segment(segment_id: str, fields: dict) -> dict | None:
    pairs = [(key, value) for key, value in fields.items() if key in {"start_seconds", "end_seconds", "override_text"} and value is not None]
    if pairs:
        pairs.append(("manually_edited", 1))
        with connect() as db:
            db.execute(f"UPDATE caption_segments SET {', '.join(f'{key}=?' for key, _ in pairs)} WHERE id=?", [value for _, value in pairs] + [segment_id])
    with connect() as db:
        row = db.execute("SELECT track_id FROM caption_segments WHERE id=?", (segment_id,)).fetchone()
    return get_track(row["track_id"]) if row else None


def update_word(word_id: str, text: str) -> dict | None:
    with connect() as db:
        db.execute("UPDATE caption_words SET text=? WHERE id=?", (text.strip(), word_id))
        row = db.execute("SELECT s.track_id FROM caption_words w JOIN caption_segments s ON s.id=w.segment_id WHERE w.id=?", (word_id,)).fetchone()
    return get_track(row["track_id"]) if row else None


def reflow_track(track_id: str, grouping: dict) -> dict | None:
    config = normalize_grouping(grouping)
    with connect() as db:
        rows = db.execute("SELECT w.* FROM caption_words w JOIN caption_segments s ON s.id=w.segment_id WHERE s.track_id=? ORDER BY s.ordinal,w.ordinal", (track_id,)).fetchall()
        words = [{"start_seconds": row["start_seconds"], "end_seconds": row["end_seconds"], "text": row["text"], "confidence": row["confidence"]} for row in rows]
        _replace_segments(db, track_id, group_words(words, config))
        db.execute("UPDATE caption_tracks SET grouping_json=?,updated_at=? WHERE id=?", (json.dumps(config), utc_now(), track_id))
    return get_track(track_id)


def mark_tracks_stale(clip_id: str, start: float, end: float) -> None:
    with connect() as db:
        db.execute("UPDATE caption_tracks SET stale=CASE WHEN boundary_start_seconds != ? OR boundary_end_seconds != ? THEN 1 ELSE 0 END,updated_at=? WHERE clip_id=?", (start, end, utc_now(), clip_id))


def clear_transcriptions(clip_id: str) -> None:
    with connect() as db:
        db.execute("DELETE FROM caption_tracks WHERE clip_id=?", (clip_id,))
        db.execute("DELETE FROM transcription_runs WHERE clip_id=? AND status NOT IN ('queued','extracting','transcribing')", (clip_id,))
