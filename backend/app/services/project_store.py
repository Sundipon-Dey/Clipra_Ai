"""SQLite persistence for projects and their imported media."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from app.db.database import connect
from app.models.schemas import MediaOut, ProjectDetail, ProjectSummary

if TYPE_CHECKING:
    from app.services.media_validation import ProbedMedia


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _media_from_row(row: sqlite3.Row) -> MediaOut:
    return MediaOut(
        id=row["id"],
        project_id=row["project_id"],
        original_filename=row["original_filename"],
        size_bytes=row["size_bytes"],
        duration_seconds=row["duration_seconds"],
        width=row["width"],
        height=row["height"],
        frame_rate=row["frame_rate"],
        frame_rate_decimal=row["frame_rate_decimal"],
        video_codec=row["video_codec"],
        audio_codec=row["audio_codec"],
        has_audio=bool(row["has_audio"]),
        container_format=row["container_format"],
        preview_status=row["preview_status"],
        preview_error=row["preview_error"],
        imported_at=row["imported_at"],
        stream_url=f"/api/media/{row['id']}/stream",
        preview_stream_url=f"/api/media/{row['id']}/preview/stream",
    )


def create_project(name: str) -> ProjectSummary:
    project_id = str(uuid4())
    now = utc_now()
    with connect() as connection:
        connection.execute(
            "INSERT INTO projects(id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (project_id, name.strip(), now, now),
        )
    return ProjectSummary(id=project_id, name=name.strip(), created_at=now, updated_at=now, media_count=0)


def list_projects() -> list[ProjectSummary]:
    with connect() as connection:
        rows = connection.execute(
            """SELECT p.*, COUNT(m.id) AS media_count
               FROM projects p LEFT JOIN media m ON m.project_id = p.id
               GROUP BY p.id ORDER BY p.updated_at DESC"""
        ).fetchall()
    return [ProjectSummary(**dict(row)) for row in rows]


def project_exists(project_id: str) -> bool:
    with connect() as connection:
        return connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is not None


def delete_project(project_id: str) -> bool:
    with connect() as connection:
        if not connection.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            return False
        media_ids = [row[0] for row in connection.execute("SELECT id FROM media WHERE project_id=?", (project_id,))]
        clip_ids = [row[0] for row in connection.execute("SELECT id FROM clips WHERE project_id=?", (project_id,))]
        for clip_id in clip_ids:
            connection.execute("DELETE FROM clips WHERE id=?", (clip_id,))
        for media_id in media_ids:
            connection.execute("DELETE FROM analysis_runs WHERE media_id=?", (media_id,))
            connection.execute("DELETE FROM media WHERE id=?", (media_id,))
        connection.execute("DELETE FROM projects WHERE id=?", (project_id,))
    return True


def get_project(project_id: str) -> ProjectDetail | None:
    with connect() as connection:
        project = connection.execute(
            """SELECT p.*, COUNT(m.id) AS media_count
               FROM projects p LEFT JOIN media m ON m.project_id = p.id
               WHERE p.id = ? GROUP BY p.id""",
            (project_id,),
        ).fetchone()
        if project is None:
            return None
        media_rows = connection.execute(
            "SELECT * FROM media WHERE project_id = ? ORDER BY imported_at DESC",
            (project_id,),
        ).fetchall()
    data = dict(project)
    data["media"] = [_media_from_row(row) for row in media_rows]
    return ProjectDetail(**data)


def add_media(
    *,
    media_id: str,
    project_id: str,
    original_filename: str,
    source_relative_path: str,
    size_bytes: int,
    metadata: ProbedMedia,
) -> MediaOut:
    now = utc_now()
    with connect() as connection:
        connection.execute(
            """INSERT INTO media(
                id, project_id, original_filename, source_relative_path, size_bytes,
                duration_seconds, width, height, frame_rate, frame_rate_decimal,
                video_codec, audio_codec, has_audio, container_format, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                media_id, project_id, original_filename, source_relative_path, size_bytes,
                metadata.duration_seconds, metadata.width, metadata.height, metadata.frame_rate,
                metadata.frame_rate_decimal, metadata.video_codec, metadata.audio_codec,
                int(metadata.has_audio), metadata.container_format, now,
            ),
        )
        connection.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id))
        row = connection.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
    return _media_from_row(row)


def get_media_record(media_id: str) -> sqlite3.Row | None:
    with connect() as connection:
        return connection.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()


def update_preview(media_id: str, *, status: str, relative_path: str | None = None, error: str | None = None) -> None:
    with connect() as connection:
        connection.execute(
            """UPDATE media SET preview_status = ?, preview_relative_path = ?, preview_error = ?
               WHERE id = ?""",
            (status, relative_path, error, media_id),
        )


def get_media(media_id: str) -> MediaOut | None:
    row = get_media_record(media_id)
    return _media_from_row(row) if row else None


def create_analysis_run(*, project_id: str, media_id: str, source_size_bytes: int, model_name: str, prompt_version: str) -> str:
    run_id = str(uuid4())
    now = utc_now()
    with connect() as connection:
        connection.execute(
            """INSERT INTO analysis_runs(
                id, project_id, media_id, status, model_name, prompt_version,
                source_size_bytes, created_at
            ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)""",
            (run_id, project_id, media_id, model_name, prompt_version, source_size_bytes, now),
        )
    return run_id


def get_analysis_run_record(run_id: str):
    with connect() as connection:
        return connection.execute("SELECT * FROM analysis_runs WHERE id = ?", (run_id,)).fetchone()


def get_latest_analysis_record(media_id: str):
    with connect() as connection:
        return connection.execute(
            "SELECT * FROM analysis_runs WHERE media_id = ? ORDER BY created_at DESC LIMIT 1", (media_id,)
        ).fetchone()


def list_analysis_records(media_id: str):
    with connect() as connection:
        return connection.execute(
            "SELECT * FROM analysis_runs WHERE media_id = ? ORDER BY created_at DESC", (media_id,)
        ).fetchall()


def list_queued_analysis_ids() -> list[str]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT id FROM analysis_runs WHERE status = 'queued' ORDER BY created_at"
        ).fetchall()
    return [row["id"] for row in rows]


def list_interrupted_cleanup_records():
    with connect() as connection:
        return connection.execute(
            """SELECT id, remote_file_name, remote_interaction_id FROM analysis_runs
               WHERE status = 'interrupted' AND cleanup_pending = 1
               AND ((remote_file_name IS NOT NULL AND remote_file_name <> '')
                 OR (remote_interaction_id IS NOT NULL AND remote_interaction_id <> ''))"""
        ).fetchall()


def list_queued_analysis_ids() -> list[str]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT id FROM analysis_runs WHERE status = 'queued' ORDER BY created_at"
        ).fetchall()
    return [row["id"] for row in rows]


def analysis_candidates(run_id: str):
    with connect() as connection:
        return connection.execute(
            "SELECT * FROM analysis_candidates WHERE analysis_id = ? ORDER BY ordinal", (run_id,)
        ).fetchall()


def update_analysis_status(
    run_id: str,
    status: str,
    *,
    started_at: str | None = None,
    completed_at: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    remote_file_name: str | None = None,
    remote_interaction_id: str | None = None,
    cleanup_pending: bool | None = None,
) -> None:
    fields = ["status = ?", "error_code = ?", "error_message = ?"]
    values: list[object] = [status, error_code, error_message]
    for field, value in (
        ("started_at", started_at), ("completed_at", completed_at),
        ("remote_file_name", remote_file_name), ("remote_interaction_id", remote_interaction_id),
    ):
        if value is not None:
            fields.append(f"{field} = ?")
            values.append(value)
    if cleanup_pending is not None:
        fields.append("cleanup_pending = ?")
        values.append(int(cleanup_pending))
    values.append(run_id)
    with connect() as connection:
        connection.execute(f"UPDATE analysis_runs SET {', '.join(fields)} WHERE id = ?", values)


def update_analysis_cleanup_state(
    run_id: str,
    *,
    cleanup_pending: bool,
    remote_file_name: str | None = None,
    remote_interaction_id: str | None = None,
) -> None:
    fields = ["cleanup_pending = ?"]
    values: list[object] = [int(cleanup_pending)]
    if remote_file_name is not None:
        fields.append("remote_file_name = ?")
        values.append(remote_file_name)
    if remote_interaction_id is not None:
        fields.append("remote_interaction_id = ?")
        values.append(remote_interaction_id)
    values.append(run_id)
    with connect() as connection:
        connection.execute(f"UPDATE analysis_runs SET {', '.join(fields)} WHERE id = ?", values)


def store_analysis_candidates(run_id: str, candidates: list[dict[str, object]]) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM analysis_candidates WHERE analysis_id = ?", (run_id,))
        connection.executemany(
            """INSERT INTO analysis_candidates(
                id, analysis_id, ordinal, start_seconds, end_seconds, title,
                description, category, reasoning, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    str(uuid4()), run_id, ordinal, candidate["start_seconds"], candidate["end_seconds"],
                    candidate["title"], candidate["description"], candidate["category"],
                    candidate["reasoning"], candidate.get("confidence"),
                )
                for ordinal, candidate in enumerate(candidates)
            ],
        )
