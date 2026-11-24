"""SQLite state for explicitly approved Instagram Reels publications."""
from __future__ import annotations

from uuid import uuid4

from app.db.database import connect
from app.services.project_store import utc_now


def create(*, render_job_id: str, generation_id: str, account: dict[str, str]) -> dict:
    upload_id, now = str(uuid4()), utc_now()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM instagram_uploads WHERE status IN ('queued','uploading') LIMIT 1").fetchone():
            raise RuntimeError("An Instagram upload is already in progress. Wait for it to finish before starting another.")
        db.execute(
            "INSERT INTO instagram_uploads(id,render_job_id,generation_id,page_id,page_name,instagram_user_id,instagram_username,status,progress,stage,created_at) "
            "VALUES(?,?,?,?,?,?,?,'queued',0,'queued',?)",
            (upload_id, render_job_id, generation_id, account["page_id"], account["page_name"],
             account["instagram_user_id"], account["instagram_username"], now),
        )
    return get(upload_id)


def get(upload_id: str) -> dict | None:
    with connect() as db:
        row = db.execute("SELECT * FROM instagram_uploads WHERE id=?", (upload_id,)).fetchone()
    return dict(row) if row else None


def list_for_render(render_job_id: str) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT * FROM instagram_uploads WHERE render_job_id=? ORDER BY created_at DESC", (render_job_id,)).fetchall()
    return [dict(row) for row in rows]


def start(upload_id: str) -> bool:
    with connect() as db:
        return db.execute("UPDATE instagram_uploads SET status='uploading',stage='uploading_to_r2',started_at=? WHERE id=? AND status='queued'",
                          (utc_now(), upload_id)).rowcount == 1


def set_r2_object(upload_id: str, key: str) -> None:
    with connect() as db:
        db.execute("UPDATE instagram_uploads SET r2_object_key=? WHERE id=? AND status='uploading'", (key, upload_id))


def set_container(upload_id: str, container_id: str) -> None:
    with connect() as db:
        db.execute("UPDATE instagram_uploads SET container_id=?,stage='processing_video' WHERE id=? AND status='uploading'", (container_id, upload_id))


def progress(upload_id: str, value: float, stage: str) -> None:
    with connect() as db:
        db.execute("UPDATE instagram_uploads SET progress=?,stage=? WHERE id=? AND status='uploading'",
                   (max(0, min(1, value)), stage[:80], upload_id))


def finish(upload_id: str, media_id: str, permalink: str | None) -> None:
    with connect() as db:
        db.execute("UPDATE instagram_uploads SET status='completed',stage='completed',progress=1,media_id=?,permalink=?,completed_at=? WHERE id=?",
                   (media_id, permalink, utc_now(), upload_id))


def fail(upload_id: str, message: str) -> None:
    with connect() as db:
        db.execute("UPDATE instagram_uploads SET status='failed',stage='failed',error_message=?,completed_at=? WHERE id=? AND status NOT IN ('completed','interrupted')",
                   (message, utc_now(), upload_id))


def interrupt_active() -> None:
    with connect() as db:
        db.execute("UPDATE instagram_uploads SET status='interrupted',stage='interrupted',error_message='Upload was interrupted by an application restart. It was not automatically retried; check Instagram before trying again.',completed_at=? WHERE status IN ('queued','uploading')",
                   (utc_now(),))
