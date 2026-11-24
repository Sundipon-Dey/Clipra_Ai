"""SQLite schema and small transaction helpers."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.core.config import settings


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    settings.ensure_directories()
    connection = sqlite3.connect(settings.database_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with connect() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 100),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS media (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
                original_filename TEXT NOT NULL,
                source_relative_path TEXT NOT NULL UNIQUE,
                size_bytes INTEGER NOT NULL CHECK(size_bytes > 0),
                duration_seconds REAL NOT NULL CHECK(duration_seconds > 0),
                width INTEGER NOT NULL CHECK(width > 0),
                height INTEGER NOT NULL CHECK(height > 0),
                frame_rate TEXT,
                frame_rate_decimal REAL,
                video_codec TEXT NOT NULL,
                audio_codec TEXT,
                has_audio INTEGER NOT NULL CHECK(has_audio IN (0, 1)),
                container_format TEXT NOT NULL,
                preview_status TEXT NOT NULL DEFAULT 'not_requested'
                    CHECK(preview_status IN ('not_requested', 'processing', 'ready', 'failed')),
                preview_relative_path TEXT UNIQUE,
                preview_error TEXT,
                imported_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS ix_media_project_id ON media(project_id);
            """
        )
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS analysis_runs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
                media_id TEXT NOT NULL REFERENCES media(id) ON DELETE RESTRICT,
                status TEXT NOT NULL CHECK(status IN (
                    'queued', 'uploading', 'processing_file', 'analyzing',
                    'completed', 'failed', 'interrupted'
                )),
                model_name TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                source_size_bytes INTEGER NOT NULL CHECK(source_size_bytes > 0),
                started_at TEXT,
                completed_at TEXT,
                error_code TEXT,
                error_message TEXT,
                remote_file_name TEXT,
                remote_interaction_id TEXT,
                cleanup_pending INTEGER NOT NULL DEFAULT 0 CHECK(cleanup_pending IN (0, 1)),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS analysis_candidates (
                id TEXT PRIMARY KEY,
                analysis_id TEXT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                start_seconds REAL NOT NULL CHECK(start_seconds >= 0),
                end_seconds REAL NOT NULL CHECK(end_seconds > start_seconds),
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                reasoning TEXT NOT NULL,
                confidence REAL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
                UNIQUE(analysis_id, ordinal)
            );

            CREATE INDEX IF NOT EXISTS ix_analysis_runs_media ON analysis_runs(media_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS ix_analysis_runs_queue ON analysis_runs(status, created_at);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_analysis_one_active_per_media
                ON analysis_runs(media_id) WHERE status IN ('queued', 'uploading', 'processing_file', 'analyzing');
            CREATE INDEX IF NOT EXISTS ix_analysis_candidates_run ON analysis_candidates(analysis_id, ordinal);
            CREATE TABLE IF NOT EXISTS clips (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
                media_id TEXT NOT NULL REFERENCES media(id) ON DELETE RESTRICT,
                source_candidate_id TEXT REFERENCES analysis_candidates(id) ON DELETE SET NULL,
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 160),
                start_seconds REAL NOT NULL CHECK(start_seconds >= 0),
                end_seconds REAL NOT NULL CHECK(end_seconds > start_seconds),
                workflow_status TEXT NOT NULL DEFAULT 'draft',
                framing_mode TEXT NOT NULL DEFAULT 'fit'
                    CHECK(framing_mode IN ('smart_crop', 'fit', 'blurred_background', 'manual_crop')),
                recommended_framing_mode TEXT
                    CHECK(recommended_framing_mode IS NULL OR recommended_framing_mode IN ('smart_crop', 'fit', 'blurred_background', 'manual_crop')),
                manual_focus_x REAL NOT NULL DEFAULT 0.5 CHECK(manual_focus_x BETWEEN 0 AND 1),
                manual_focus_y REAL NOT NULL DEFAULT 0.5 CHECK(manual_focus_y BETWEEN 0 AND 1),
                manual_zoom REAL NOT NULL DEFAULT 1.0 CHECK(manual_zoom BETWEEN 1 AND 3),
                blur_strength REAL NOT NULL DEFAULT 18 CHECK(blur_strength BETWEEN 0 AND 40),
                framing_status TEXT NOT NULL DEFAULT 'not_requested'
                    CHECK(framing_status IN ('not_requested', 'pending', 'completed', 'failed')),
                framing_error_code TEXT,
                framing_error_message TEXT,
                framing_model TEXT,
                framing_requested_at TEXT,
                framing_completed_at TEXT,
                framing_start_seconds REAL,
                framing_end_seconds REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clip_focal_points (
                id TEXT PRIMARY KEY,
                clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                time_seconds REAL NOT NULL CHECK(time_seconds >= 0),
                x REAL NOT NULL CHECK(x BETWEEN 0 AND 1),
                y REAL NOT NULL CHECK(y BETWEEN 0 AND 1),
                confidence REAL CHECK(confidence IS NULL OR confidence BETWEEN 0 AND 1),
                UNIQUE(clip_id, ordinal)
            );

            CREATE INDEX IF NOT EXISTS ix_clips_media ON clips(media_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS ix_clips_project ON clips(project_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS ix_clip_focal_points_clip ON clip_focal_points(clip_id, ordinal);
            CREATE TABLE IF NOT EXISTS transcription_runs (
                id TEXT PRIMARY KEY,
                clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
                media_id TEXT NOT NULL REFERENCES media(id) ON DELETE RESTRICT,
                status TEXT NOT NULL CHECK(status IN ('queued', 'extracting', 'transcribing', 'completed', 'failed', 'interrupted')),
                model_id TEXT NOT NULL,
                language TEXT NOT NULL,
                device_profile TEXT NOT NULL,
                clip_start_seconds REAL NOT NULL CHECK(clip_start_seconds >= 0),
                clip_end_seconds REAL NOT NULL CHECK(clip_end_seconds > clip_start_seconds),
                started_at TEXT,
                completed_at TEXT,
                error_code TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_transcription_runs_clip ON transcription_runs(clip_id, created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_transcription_active_per_clip
                ON transcription_runs(clip_id) WHERE status IN ('queued', 'extracting', 'transcribing');

            CREATE TABLE IF NOT EXISTS caption_tracks (
                id TEXT PRIMARY KEY,
                clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
                transcription_run_id TEXT REFERENCES transcription_runs(id) ON DELETE SET NULL,
                name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 160),
                language TEXT NOT NULL DEFAULT 'en',
                preset_id TEXT NOT NULL,
                style_version INTEGER NOT NULL DEFAULT 1,
                style_json TEXT NOT NULL,
                grouping_json TEXT NOT NULL,
                position_x REAL NOT NULL DEFAULT 0.5 CHECK(position_x BETWEEN 0 AND 1),
                position_y REAL NOT NULL DEFAULT 0.76 CHECK(position_y BETWEEN 0 AND 1),
                safe_zone_profile TEXT NOT NULL DEFAULT 'shorts',
                timing_offset_seconds REAL NOT NULL DEFAULT 0,
                boundary_start_seconds REAL NOT NULL,
                boundary_end_seconds REAL NOT NULL,
                stale INTEGER NOT NULL DEFAULT 0 CHECK(stale IN (0,1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_caption_tracks_clip ON caption_tracks(clip_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS caption_segments (
                id TEXT PRIMARY KEY,
                track_id TEXT NOT NULL REFERENCES caption_tracks(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                start_seconds REAL NOT NULL CHECK(start_seconds >= 0),
                end_seconds REAL NOT NULL CHECK(end_seconds > start_seconds),
                generated_text TEXT NOT NULL,
                override_text TEXT,
                manually_edited INTEGER NOT NULL DEFAULT 0 CHECK(manually_edited IN (0,1)),
                UNIQUE(track_id, ordinal)
            );
            CREATE TABLE IF NOT EXISTS caption_words (
                id TEXT PRIMARY KEY,
                segment_id TEXT NOT NULL REFERENCES caption_segments(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                start_seconds REAL NOT NULL CHECK(start_seconds >= 0),
                end_seconds REAL NOT NULL CHECK(end_seconds >= start_seconds),
                original_text TEXT NOT NULL,
                text TEXT NOT NULL,
                confidence REAL CHECK(confidence IS NULL OR confidence BETWEEN 0 AND 1),
                UNIQUE(segment_id, ordinal)
            );
            CREATE INDEX IF NOT EXISTS ix_caption_segments_track ON caption_segments(track_id, ordinal);
            CREATE INDEX IF NOT EXISTS ix_caption_words_segment ON caption_words(segment_id, ordinal);
            CREATE TABLE IF NOT EXISTS render_jobs (
                id TEXT PRIMARY KEY,
                clip_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('preview','export')),
                status TEXT NOT NULL CHECK(status IN ('queued','processing','completed','failed','cancelled','interrupted','stale')),
                snapshot_json TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                stage TEXT NOT NULL DEFAULT 'queued',
                error_message TEXT,
                output_relative_path TEXT,
                output_bytes INTEGER,
                version_number INTEGER,
                approved_at TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_render_jobs_clip ON render_jobs(clip_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS ix_render_jobs_queue ON render_jobs(status, created_at);
            CREATE TABLE IF NOT EXISTS clip_layout_assets (
                id TEXT PRIMARY KEY,
                clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
                relative_path TEXT NOT NULL UNIQUE,
                original_filename TEXT NOT NULL,
                content_type TEXT NOT NULL CHECK(content_type IN ('image/png','image/jpeg','image/webp')),
                size_bytes INTEGER NOT NULL CHECK(size_bytes > 0),
                width INTEGER NOT NULL CHECK(width > 0),
                height INTEGER NOT NULL CHECK(height > 0),
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_clip_layout_assets_clip ON clip_layout_assets(clip_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS clipwing_imports (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                video_url TEXT NOT NULL,
                analysis_text TEXT NOT NULL,
                video_title TEXT,
                video_duration_seconds REAL,
                formats_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL CHECK(status IN ('queued','downloading','cutting','completed','completed_with_errors','failed','interrupted')),
                stage TEXT NOT NULL DEFAULT 'queued',
                progress REAL NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 1),
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_clipwing_imports_project ON clipwing_imports(project_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS ix_clipwing_imports_queue ON clipwing_imports(status, created_at);
            CREATE TABLE IF NOT EXISTS clipwing_entries (
                id TEXT PRIMARY KEY,
                import_id TEXT NOT NULL REFERENCES clipwing_imports(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 160),
                start_seconds REAL NOT NULL CHECK(start_seconds >= 0),
                end_seconds REAL NOT NULL CHECK(end_seconds > start_seconds),
                score REAL CHECK(score IS NULL OR (score >= 0 AND score <= 100)),
                transcript TEXT,
                caption_source TEXT NOT NULL DEFAULT 'none' CHECK(caption_source IN ('none','youtube')),
                selected_format_id TEXT,
                video_url TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued','cutting','ready','failed','interrupted')),
                progress REAL NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 1),
                error_message TEXT,
                media_id TEXT REFERENCES media(id) ON DELETE SET NULL,
                clip_id TEXT REFERENCES clips(id) ON DELETE SET NULL,
                UNIQUE(import_id, ordinal)
            );
            CREATE INDEX IF NOT EXISTS ix_clipwing_entries_import ON clipwing_entries(import_id, ordinal);
            CREATE TABLE IF NOT EXISTS social_content_generations (
                id TEXT PRIMARY KEY,
                render_job_id TEXT NOT NULL REFERENCES render_jobs(id) ON DELETE RESTRICT,
                status TEXT NOT NULL CHECK(status IN ('queued','uploading','processing_file','generating','completed','failed','interrupted')),
                progress REAL NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 1),
                stage TEXT NOT NULL DEFAULT 'queued',
                model_name TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                consent_at TEXT NOT NULL,
                context_json TEXT NOT NULL,
                packages_json TEXT,
                edited_packages_json TEXT NOT NULL DEFAULT '{}',
                error_code TEXT,
                error_message TEXT,
                remote_file_name TEXT,
                remote_interaction_id TEXT,
                cleanup_pending INTEGER NOT NULL DEFAULT 0 CHECK(cleanup_pending IN (0,1)),
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_social_content_export ON social_content_generations(render_job_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS ix_social_content_queue ON social_content_generations(status, created_at);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_social_content_active_per_export
                ON social_content_generations(render_job_id) WHERE status IN ('queued','uploading','processing_file','generating');
            CREATE TABLE IF NOT EXISTS youtube_uploads (
                id TEXT PRIMARY KEY,
                render_job_id TEXT NOT NULL REFERENCES render_jobs(id) ON DELETE RESTRICT,
                generation_id TEXT NOT NULL REFERENCES social_content_generations(id) ON DELETE RESTRICT,
                status TEXT NOT NULL CHECK(status IN ('queued','uploading','completed','failed','interrupted')),
                progress REAL NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 1),
                stage TEXT NOT NULL DEFAULT 'queued',
                privacy_status TEXT NOT NULL CHECK(privacy_status IN ('private','unlisted','public')),
                video_id TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_youtube_uploads_render ON youtube_uploads(render_job_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS ix_youtube_uploads_status ON youtube_uploads(status, created_at);
            CREATE TABLE IF NOT EXISTS facebook_uploads (
                id TEXT PRIMARY KEY,
                render_job_id TEXT NOT NULL REFERENCES render_jobs(id) ON DELETE RESTRICT,
                generation_id TEXT NOT NULL REFERENCES social_content_generations(id) ON DELETE RESTRICT,
                page_id TEXT NOT NULL,
                page_name TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued','uploading','completed','failed','interrupted')),
                progress REAL NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 1),
                stage TEXT NOT NULL DEFAULT 'queued',
                video_id TEXT,
                post_id TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_facebook_uploads_render ON facebook_uploads(render_job_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS ix_facebook_uploads_status ON facebook_uploads(status, created_at);
            CREATE TABLE IF NOT EXISTS instagram_uploads (
                id TEXT PRIMARY KEY,
                render_job_id TEXT NOT NULL REFERENCES render_jobs(id) ON DELETE RESTRICT,
                generation_id TEXT NOT NULL REFERENCES social_content_generations(id) ON DELETE RESTRICT,
                page_id TEXT NOT NULL,
                page_name TEXT NOT NULL,
                instagram_user_id TEXT NOT NULL,
                instagram_username TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued','uploading','completed','failed','interrupted')),
                progress REAL NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 1),
                stage TEXT NOT NULL DEFAULT 'queued',
                media_id TEXT,
                permalink TEXT,
                container_id TEXT,
                r2_object_key TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_instagram_uploads_render ON instagram_uploads(render_job_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS ix_instagram_uploads_status ON instagram_uploads(status, created_at);
            PRAGMA user_version = 18;
            """
        )
        clip_columns = {row["name"] for row in connection.execute("PRAGMA table_info(clips)").fetchall()}
        import_columns = {row["name"] for row in connection.execute("PRAGMA table_info(clipwing_imports)").fetchall()}
        if "video_title" not in import_columns:
            connection.execute("ALTER TABLE clipwing_imports ADD COLUMN video_title TEXT")
        if "video_duration_seconds" not in import_columns:
            connection.execute("ALTER TABLE clipwing_imports ADD COLUMN video_duration_seconds REAL")
        if "formats_json" not in import_columns:
            connection.execute("ALTER TABLE clipwing_imports ADD COLUMN formats_json TEXT NOT NULL DEFAULT '[]'")
        entry_columns = {row["name"] for row in connection.execute("PRAGMA table_info(clipwing_entries)").fetchall()}
        if "selected_format_id" not in entry_columns:
            connection.execute("ALTER TABLE clipwing_entries ADD COLUMN selected_format_id TEXT")
        if "framing_start_seconds" not in clip_columns:
            connection.execute("ALTER TABLE clips ADD COLUMN framing_start_seconds REAL")
        if "framing_end_seconds" not in clip_columns:
            connection.execute("ALTER TABLE clips ADD COLUMN framing_end_seconds REAL")
        instagram_columns = {row["name"] for row in connection.execute("PRAGMA table_info(instagram_uploads)").fetchall()}
        if "diagnostic_variant" in instagram_columns:
            connection.execute("ALTER TABLE instagram_uploads DROP COLUMN diagnostic_variant")
        if "container_id" not in instagram_columns:
            connection.execute("ALTER TABLE instagram_uploads ADD COLUMN container_id TEXT")
        if "r2_object_key" not in instagram_columns:
            connection.execute("ALTER TABLE instagram_uploads ADD COLUMN r2_object_key TEXT")
        connection.execute("PRAGMA user_version = 18")
        if "fit_background_color" not in clip_columns:
            connection.execute("ALTER TABLE clips ADD COLUMN fit_background_color TEXT NOT NULL DEFAULT '#090a0f'")
        if "manual_override_enabled" not in clip_columns:
            connection.execute("ALTER TABLE clips ADD COLUMN manual_override_enabled INTEGER NOT NULL DEFAULT 0 CHECK(manual_override_enabled IN (0,1))")
        if "layout_type" not in clip_columns:
            connection.execute("ALTER TABLE clips ADD COLUMN layout_type TEXT NOT NULL DEFAULT 'original' CHECK(layout_type IN ('original','split_streamer_gameplay'))")
        if "split_layout_json" not in clip_columns:
            connection.execute("ALTER TABLE clips ADD COLUMN split_layout_json TEXT NOT NULL DEFAULT '{}'")
        if "vertical_crop_percent" not in clip_columns:
            connection.execute("ALTER TABLE clips ADD COLUMN vertical_crop_percent REAL NOT NULL DEFAULT 0 CHECK(vertical_crop_percent BETWEEN 0 AND 40)")
        if "custom_text_json" not in clip_columns:
            connection.execute("ALTER TABLE clips ADD COLUMN custom_text_json TEXT NOT NULL DEFAULT '{}'")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(analysis_runs)").fetchall()}
        if "remote_interaction_id" not in columns:
            connection.execute("ALTER TABLE analysis_runs ADD COLUMN remote_interaction_id TEXT")
        connection.execute(
            "UPDATE media SET preview_status='failed', preview_error='Preview generation was interrupted.' "
            "WHERE preview_status='processing'"
        )
        connection.execute(
            "UPDATE transcription_runs SET status='interrupted', completed_at=CURRENT_TIMESTAMP, "
            "error_code='process_restarted', error_message='Local transcription was interrupted by an application restart.' "
            "WHERE status IN ('extracting', 'transcribing')"
        )
        connection.execute(
            "UPDATE clips SET framing_status='failed', framing_error_code='process_restarted', "
            "framing_error_message='The framing recommendation was interrupted by an application restart.', "
            "framing_completed_at=CURRENT_TIMESTAMP WHERE framing_status='pending'"
        )
        # A queued job is safe to resume because no Gemini request has been sent.
        # Any job that reached an external-call stage is left interrupted to avoid
        # silently repeating a potentially billable request after a restart.
        connection.execute(
            "UPDATE analysis_runs SET status='interrupted', completed_at=CURRENT_TIMESTAMP, "
            "cleanup_pending=CASE WHEN (remote_file_name IS NOT NULL AND remote_file_name <> '') "
            "OR (remote_interaction_id IS NOT NULL AND remote_interaction_id <> '') THEN 1 ELSE cleanup_pending END, "
            "error_code='process_restarted', error_message='Analysis was interrupted by an application restart.' "
            "WHERE status IN ('uploading', 'processing_file', 'analyzing')"
        )
