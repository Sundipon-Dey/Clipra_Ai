"""Durable Stage 6 generations, platform packages, and user edits."""
from __future__ import annotations

import json
from uuid import uuid4

from app.db.database import connect
from app.services.project_store import utc_now


def _decode(row) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    result["cleanup_pending"] = bool(result["cleanup_pending"])
    result["context"] = json.loads(result.pop("context_json"))
    generated = result.pop("packages_json")
    result["generated_packages"] = json.loads(generated) if generated else None
    result["edited_packages"] = json.loads(result.pop("edited_packages_json") or "{}")
    return result


def get(generation_id: str) -> dict | None:
    with connect() as db:
        return _decode(db.execute("SELECT * FROM social_content_generations WHERE id=?", (generation_id,)).fetchone())


def list_for_export(render_job_id: str) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT * FROM social_content_generations WHERE render_job_id=? ORDER BY created_at DESC", (render_job_id,)).fetchall()
    return [_decode(row) for row in rows]


def create(*, render_job_id: str, model_name: str, prompt_version: str, consent_at: str, context: dict) -> str:
    generation_id, now = str(uuid4()), utc_now()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """INSERT INTO social_content_generations
               (id,render_job_id,status,progress,stage,model_name,prompt_version,consent_at,context_json,created_at)
               VALUES(?,?,'queued',0,'queued',?,?,?,?,?)""",
            (generation_id, render_job_id, model_name, prompt_version, consent_at,
             json.dumps(context, ensure_ascii=False, separators=(",", ":")), now),
        )
    return generation_id


def start(generation_id: str) -> bool:
    with connect() as db:
        return db.execute(
            "UPDATE social_content_generations SET status='uploading',stage='uploading',progress=0.08,started_at=? WHERE id=? AND status='queued'",
            (utc_now(), generation_id),
        ).rowcount == 1


def update_status(generation_id: str, status: str, stage: str, progress: float) -> None:
    with connect() as db:
        db.execute(
            "UPDATE social_content_generations SET status=?,stage=?,progress=? WHERE id=? AND status IN ('uploading','processing_file','generating')",
            (status, stage[:80], max(0, min(1, progress)), generation_id),
        )


def set_remote(generation_id: str, *, file_name: str | None = None, interaction_id: str | None = None) -> None:
    with connect() as db:
        db.execute(
            "UPDATE social_content_generations SET remote_file_name=COALESCE(?,remote_file_name),remote_interaction_id=COALESCE(?,remote_interaction_id),cleanup_pending=1 WHERE id=?",
            (file_name, interaction_id, generation_id),
        )


def finish(generation_id: str, packages: dict) -> None:
    with connect() as db:
        db.execute(
            "UPDATE social_content_generations SET status='completed',stage='completed',progress=1,packages_json=?,completed_at=? WHERE id=?",
            (json.dumps(packages, ensure_ascii=False, separators=(",", ":")), utc_now(), generation_id),
        )


def fail(generation_id: str, *, code: str, message: str) -> None:
    with connect() as db:
        db.execute(
            "UPDATE social_content_generations SET status='failed',stage='failed',error_code=?,error_message=?,completed_at=? WHERE id=? AND status NOT IN ('completed','interrupted')",
            (code[:80], message[:1000], utc_now(), generation_id),
        )


def save_package(generation_id: str, platform: str, content: dict) -> dict | None:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT edited_packages_json,status FROM social_content_generations WHERE id=?", (generation_id,)).fetchone()
        if not row or row["status"] != "completed":
            return None
        edited = json.loads(row["edited_packages_json"] or "{}")
        edited[platform] = content
        db.execute("UPDATE social_content_generations SET edited_packages_json=? WHERE id=?",
                   (json.dumps(edited, ensure_ascii=False, separators=(",", ":")), generation_id))
    return get(generation_id)


def import_manual_packages(generation_id: str, packages: dict) -> dict | None:
    """Complete a failed attempt with user-supplied, already-validated packages."""
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status FROM social_content_generations WHERE id=?", (generation_id,)).fetchone()
        if not row or row["status"] != "failed":
            return None
        db.execute(
            """UPDATE social_content_generations
               SET status='completed',stage='completed',progress=1,model_name='manual-fallback',
                   prompt_version='stage6-social-manual-v1',packages_json=?,edited_packages_json='{}',
                   error_code=NULL,error_message=NULL,completed_at=?
               WHERE id=? AND status='failed'""",
            (json.dumps(packages, ensure_ascii=False, separators=(",", ":")), utc_now(), generation_id),
        )
    return get(generation_id)


def recovery_state() -> tuple[list[str], list[str]]:
    """Resume never-started work; interrupt active paid work and return cleanup ids."""
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        cleanup = [row[0] for row in db.execute(
            "SELECT id FROM social_content_generations WHERE cleanup_pending=1 AND (remote_file_name IS NOT NULL OR remote_interaction_id IS NOT NULL)"
        ).fetchall()]
        db.execute(
            "UPDATE social_content_generations SET status='interrupted',stage='interrupted',error_code='process_restarted',error_message='Generation was interrupted during a Google request. Start a new generation explicitly to retry.',completed_at=? WHERE status IN ('uploading','processing_file','generating')",
            (utc_now(),),
        )
        queued = [row[0] for row in db.execute("SELECT id FROM social_content_generations WHERE status='queued' ORDER BY created_at").fetchall()]
    return queued, cleanup


def clear_cleanup(generation_id: str, *, file_done: bool, interaction_done: bool) -> None:
    with connect() as db:
        db.execute(
            "UPDATE social_content_generations SET remote_file_name=?,remote_interaction_id=?,cleanup_pending=? WHERE id=?",
            (None if file_done else _keep_remote(generation_id, "remote_file_name"),
             None if interaction_done else _keep_remote(generation_id, "remote_interaction_id"),
             0 if file_done and interaction_done else 1, generation_id),
        )


def _keep_remote(generation_id: str, column: str):
    if column not in {"remote_file_name", "remote_interaction_id"}:
        raise ValueError("invalid cleanup column")
    with connect() as db:
        row = db.execute(f"SELECT {column} FROM social_content_generations WHERE id=?", (generation_id,)).fetchone()
    return row[0] if row else None
