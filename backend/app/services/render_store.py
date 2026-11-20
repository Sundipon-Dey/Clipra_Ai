"""Durable, immutable Stage 5 render job records."""
from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from app.db.database import connect
from app.services.project_store import utc_now


def digest(snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def create(*, clip_id: str, project_id: str, kind: str, snapshot: dict, version: int | None = None, approved_at: str | None = None) -> dict:
    job_id, now = str(uuid4()), utc_now()
    raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    with connect() as db:
        db.execute("INSERT INTO render_jobs(id,clip_id,project_id,kind,status,snapshot_json,config_hash,version_number,approved_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (job_id, clip_id, project_id, kind, "queued", raw, digest(snapshot), version, approved_at, now))
    return get(job_id)


def get(job_id: str) -> dict | None:
    with connect() as db:
        row = db.execute("SELECT * FROM render_jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_for_clip(clip_id: str) -> list[dict]:
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM render_jobs WHERE clip_id=? ORDER BY created_at DESC", (clip_id,)).fetchall()]


def set_progress(job_id: str, progress: float, stage: str) -> None:
    with connect() as db:
        db.execute("UPDATE render_jobs SET progress=?,stage=? WHERE id=? AND status='processing'", (max(0, min(1, progress)), stage[:80], job_id))


def start(job_id: str) -> None:
    with connect() as db:
        db.execute("UPDATE render_jobs SET status='processing',stage='rendering',started_at=? WHERE id=? AND status='queued'", (utc_now(), job_id))


def finish(job_id: str, *, relative: str, size: int) -> None:
    now = utc_now()
    with connect() as db:
        db.execute("UPDATE render_jobs SET status='completed',progress=1,stage='completed',output_relative_path=?,output_bytes=?,completed_at=? WHERE id=?", (relative, size, now, job_id))


def fail(job_id: str, message: str) -> None:
    with connect() as db:
        db.execute("UPDATE render_jobs SET status='failed',stage='failed',error_message=?,completed_at=? WHERE id=?", (message[:1000], utc_now(), job_id))


def next_version(clip_id: str) -> int:
    with connect() as db:
        return int(db.execute("SELECT COALESCE(MAX(version_number),0)+1 FROM render_jobs WHERE clip_id=? AND kind='export'", (clip_id,)).fetchone()[0])


def recover() -> list[str]:
    with connect() as db:
        db.execute("UPDATE render_jobs SET status='interrupted',stage='interrupted',error_message='Rendering was interrupted by application restart.',completed_at=? WHERE status='processing'", (utc_now(),))
        return [row[0] for row in db.execute("SELECT id FROM render_jobs WHERE status='queued' ORDER BY created_at").fetchall()]
