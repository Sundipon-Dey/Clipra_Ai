"""SQLite persistence for explicitly approved per-export Facebook Reels uploads."""
from __future__ import annotations

from uuid import uuid4

from app.db.database import connect
from app.services.project_store import utc_now


def create(*, render_job_id: str, generation_id: str, page_id: str, page_name: str) -> dict:
    upload_id, now = str(uuid4()), utc_now()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM facebook_uploads WHERE status IN ('queued','uploading') LIMIT 1").fetchone():
            raise RuntimeError("A Facebook upload is already in progress. Wait for it to finish before starting another.")
        db.execute("INSERT INTO facebook_uploads(id,render_job_id,generation_id,page_id,page_name,status,progress,stage,created_at) VALUES(?,?,?,?,?,'queued',0,'queued',?)",
                   (upload_id, render_job_id, generation_id, page_id, page_name, now))
    return get(upload_id)


def get(upload_id: str) -> dict | None:
    with connect() as db:
        row = db.execute("SELECT * FROM facebook_uploads WHERE id=?", (upload_id,)).fetchone()
    return dict(row) if row else None


def list_for_render(render_job_id: str) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT * FROM facebook_uploads WHERE render_job_id=? ORDER BY created_at DESC", (render_job_id,)).fetchall()
    return [dict(row) for row in rows]


def start(upload_id: str) -> bool:
    with connect() as db:
        return db.execute("UPDATE facebook_uploads SET status='uploading',stage='starting_upload',started_at=? WHERE id=? AND status='queued'", (utc_now(), upload_id)).rowcount == 1


def progress(upload_id: str, value: float, stage: str) -> None:
    with connect() as db:
        db.execute("UPDATE facebook_uploads SET progress=?,stage=? WHERE id=? AND status='uploading'", (max(0, min(1, value)), stage[:80], upload_id))


def finish(upload_id: str, video_id: str, post_id: str | None) -> None:
    with connect() as db:
        db.execute("UPDATE facebook_uploads SET status='completed',stage='completed',progress=1,video_id=?,post_id=?,completed_at=? WHERE id=?", (video_id, post_id, utc_now(), upload_id))


def fail(upload_id: str, message: str) -> None:
    with connect() as db:
        db.execute("UPDATE facebook_uploads SET status='failed',stage='failed',error_message=?,completed_at=? WHERE id=? AND status NOT IN ('completed','interrupted')", (message[:1000], utc_now(), upload_id))


def interrupt_active() -> None:
    with connect() as db:
        db.execute("UPDATE facebook_uploads SET status='interrupted',stage='interrupted',error_message='Upload was interrupted by an application restart. It was not automatically retried; check your Facebook Page before starting another upload.',completed_at=? WHERE status IN ('queued','uploading')", (utc_now(),))
