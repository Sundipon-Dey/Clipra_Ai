"""Gemini Files API video analysis and strict candidate validation."""

from __future__ import annotations

import json
import logging
import math
import mimetypes
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import errors, types
import httpx2

from app.core.config import settings
from app.services.media_validation import probe_video
from app.services.project_store import (
    get_analysis_run_record,
    get_media_record,
    store_analysis_candidates,
    update_analysis_status,
    update_analysis_cleanup_state,
    utc_now,
)
from app.services.storage import managed_path


logger = logging.getLogger(__name__)
PROMPT_VERSION = "highlight-agentic-v1"
ACTIVE_STATUSES = {"queued", "uploading", "processing_file", "analyzing"}
MAX_CANDIDATES = 15
ALLOWED_CATEGORIES = {
    "funny", "chaotic", "cinematic", "exciting", "unexpected", "action",
    "reaction", "fail", "achievement", "story",
}
MIME_BY_EXTENSION = {
    ".mp4": "video/mp4", ".mov": "video/mov", ".avi": "video/avi", ".webm": "video/webm",
}


class AnalysisFailure(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def validate_and_deduplicate_candidates(value: Any, duration_seconds: float) -> list[dict[str, Any]]:
    """Keep only well-formed, in-bounds candidates and collapse substantial overlap."""
    if not isinstance(value, dict) or not isinstance(value.get("candidates"), list):
        raise AnalysisFailure("malformed_response", "Gemini returned an unexpected response structure. Run analysis again.")

    valid: list[dict[str, Any]] = []
    for candidate in value["candidates"][:100]:
        if not isinstance(candidate, dict):
            continue
        start = candidate.get("start_seconds")
        end = candidate.get("end_seconds")
        confidence = candidate.get("confidence")
        if (
            isinstance(start, bool) or isinstance(end, bool)
            or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
            or not math.isfinite(start) or not math.isfinite(end)
            or start < 0 or end <= start or end > duration_seconds
        ):
            continue
        if confidence is not None and (
            isinstance(confidence, bool) or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence) or confidence < 0 or confidence > 1
        ):
            continue
        category = candidate.get("category")
        title = candidate.get("title")
        description = candidate.get("description")
        reasoning = candidate.get("reasoning")
        if (
            not isinstance(category, str) or category not in ALLOWED_CATEGORIES
            or not all(isinstance(item, str) and item.strip() for item in (title, description, reasoning))
        ):
            continue
        valid.append({
            "start_seconds": round(float(start), 3),
            "end_seconds": round(float(end), 3),
            "title": title.strip()[:160],
            "description": description.strip()[:600],
            "category": category,
            "reasoning": reasoning.strip()[:1000],
            "confidence": float(confidence) if confidence is not None else None,
        })

    # Prefer the model's strongest recommendations, but display the survivors in timeline order.
    ranked = sorted(valid, key=lambda item: item["confidence"] if item["confidence"] is not None else 0.5, reverse=True)
    selected: list[dict[str, Any]] = []
    for candidate in ranked:
        start, end = candidate["start_seconds"], candidate["end_seconds"]
        candidate_length = end - start
        duplicate = False
        for accepted in selected:
            overlap = max(0.0, min(end, accepted["end_seconds"]) - max(start, accepted["start_seconds"]))
            shorter_length = min(candidate_length, accepted["end_seconds"] - accepted["start_seconds"])
            if shorter_length > 0 and overlap / shorter_length >= 0.65:
                duplicate = True
                break
        if not duplicate:
            selected.append(candidate)
        if len(selected) >= MAX_CANDIDATES:
            break
    return sorted(selected, key=lambda item: item["start_seconds"])


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start_seconds": {"type": "number"},
                        "end_seconds": {"type": "number"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "category": {"type": "string", "enum": sorted(ALLOWED_CATEGORIES)},
                        "reasoning": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["start_seconds", "end_seconds", "title", "description", "category", "reasoning"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["candidates"],
        "additionalProperties": False,
    }


def _analysis_prompt(duration_seconds: float) -> str:
    return (
        "Review the supplied video to find a small set of genuinely engaging short-form moments. "
        "Scan the full timeline broadly, then use agentic video navigation to inspect promising sections "
        "more closely before choosing timestamps. Consider funny, chaotic, cinematic, exciting, unexpected, "
        "action, reaction, fail, achievement, and story moments. Return at most 15 distinct moments. "
        "Use seconds from the original video's beginning. Do not invent events or timestamps; only include "
        "moments supported by visible or audible evidence. Each interval must satisfy 0 <= start < end <= "
        f"{duration_seconds:.3f}. Prefer concise clips that contain the setup and payoff. "
        "Write a concise title, factual description, category, and why the moment may engage viewers. "
        "Confidence is a subjective recommendation, not an objective measurement; omit it when uncertain. "
        "If nothing stands out, return {\"candidates\": []}."
    )


def _error_details(error: BaseException) -> tuple[str, str]:
    if isinstance(error, errors.APIError):
        code = getattr(error, "code", None)
        status_code = getattr(error, "status_code", code)
        if status_code == 429:
            return "quota_or_rate_limit", "Gemini rate limit or quota was reached. Check AI Studio quota and try again later."
        if status_code in (401, 403):
            return "authentication", "Gemini rejected the configured API key or model access. Check backend/.env and AI Studio access."
        if status_code in (400, 415):
            return "unsupported_media_or_request", "Gemini could not process this video or analysis request. Check supported media limits and format."
        if status_code == 504:
            return "timeout", "Gemini did not finish the request before the configured timeout. No automatic retry was made."
        return "gemini_api_error", f"Gemini returned an API error (HTTP {status_code}). No automatic retry was made."
    if isinstance(error, (TimeoutError, OSError, httpx2.TimeoutException)):
        return "timeout_or_network", "The Gemini request timed out or could not reach Google. No automatic retry was made."
    return "analysis_failed", "Video analysis failed unexpectedly. No automatic retry was made. Check local logs for diagnostic details."


def _run_gemini(run_id: str, source: Path, mime_type: str, duration: float) -> list[dict[str, Any]]:
    if not settings.gemini_api_key:
        raise AnalysisFailure("not_configured", "GEMINI_API_KEY is not configured in backend/.env.")
    if source.stat().st_size > settings.gemini_file_max_bytes:
        max_gib = settings.gemini_file_max_bytes / 1024**3
        raise AnalysisFailure("file_too_large", f"Gemini Files API upload limit is configured to {max_gib:.2f} GiB per video.")

    client = genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(
            api_version="v1beta",
            timeout=settings.gemini_timeout_seconds * 1000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    remote_file = None
    remote_interaction_id = None
    try:
        update_analysis_status(run_id, "uploading", started_at=utc_now())
        remote_file = client.files.upload(
            file=source,
            config={"mime_type": mime_type, "display_name": source.name},
        )
        remote_name = remote_file.name
        update_analysis_status(run_id, "processing_file", remote_file_name=remote_name, cleanup_pending=True)
        poll_started = time.monotonic()
        while not remote_file.state or remote_file.state.name != "ACTIVE":
            state_name = remote_file.state.name if remote_file.state else "UNKNOWN"
            if state_name == "FAILED":
                raise AnalysisFailure("file_processing_failed", "Gemini could not prepare this video for analysis. No highlight request was sent.")
            if time.monotonic() - poll_started >= settings.gemini_file_poll_timeout_seconds:
                raise AnalysisFailure("file_processing_timeout", "Gemini video preparation timed out. No highlight request was sent.")
            time.sleep(3)
            remote_file = client.files.get(name=remote_name)

        update_analysis_status(run_id, "analyzing")
        interaction = client.interactions.create(
            model=settings.gemini_model,
            input=[
                {
                    "type": "video",
                    "uri": remote_file.uri,
                    "mime_type": mime_type,
                    "processing": "agentic",
                    "resolution": "low",
                },
                {"type": "text", "text": _analysis_prompt(duration)},
            ],
            response_format={"type": "text", "mime_type": "application/json", "schema": _response_schema()},
            generation_config={"temperature": 0, "max_output_tokens": settings.gemini_max_output_tokens},
            background=True,
        )
        interaction_id = getattr(interaction, "id", None)
        if not isinstance(interaction_id, str) or not interaction_id:
            raise AnalysisFailure("malformed_response", "Gemini did not return a background interaction ID.")
        update_analysis_status(run_id, "analyzing", remote_interaction_id=interaction_id)
        remote_interaction_id = interaction_id
        interaction_started = time.monotonic()
        while getattr(interaction, "status", None) == "in_progress":
            if time.monotonic() - interaction_started >= settings.gemini_interaction_timeout_seconds:
                try:
                    client.interactions.cancel(id=interaction_id)
                except Exception:
                    logger.warning("Gemini interaction cancellation is pending for analysis run %s", run_id)
                raise AnalysisFailure("analysis_timeout", "Gemini highlight analysis exceeded its time limit. No automatic retry was made.")
            time.sleep(2)
            interaction = client.interactions.get(id=interaction_id)
        final_status = getattr(interaction, "status", "completed")
        if final_status != "completed":
            raise AnalysisFailure("interaction_failed", "Gemini could not complete the video analysis. No automatic retry was made.")
        raw = getattr(interaction, "output_text", None)
        if not isinstance(raw, str) or not raw.strip():
            raise AnalysisFailure("malformed_response", "Gemini returned an empty highlight response.")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise AnalysisFailure("malformed_response", "Gemini returned invalid JSON. Run analysis again.") from error
        candidates = validate_and_deduplicate_candidates(parsed, duration)
        if parsed.get("candidates") and not candidates:
            raise AnalysisFailure("invalid_candidates", "Gemini returned no candidates with valid timestamps and fields.")
        return candidates
    finally:
        file_cleanup_failed = False
        interaction_cleanup_failed = False
        if remote_interaction_id:
            try:
                client.interactions.delete(id=remote_interaction_id)
                remote_interaction_id = ""
            except Exception:
                interaction_cleanup_failed = True
                logger.warning("Gemini interaction record cleanup is pending for analysis run %s", run_id)
        if remote_file is not None:
            try:
                client.files.delete(name=remote_file.name)
            except Exception:
                file_cleanup_failed = True
                logger.warning("Gemini temporary file cleanup is pending for analysis run %s", run_id)
            else:
                remote_file = None
        update_analysis_cleanup_state(
            run_id,
            remote_file_name=None if file_cleanup_failed else "",
            remote_interaction_id=None if interaction_cleanup_failed else remote_interaction_id,
            cleanup_pending=file_cleanup_failed or interaction_cleanup_failed,
        )
        try:
            client.close()
        except Exception:
            logger.warning("Gemini client cleanup failed for analysis run %s", run_id)


def process_analysis(run_id: str) -> None:
    record = get_analysis_run_record(run_id)
    if record is None or record["status"] != "queued":
        return
    try:
        media = get_media_record(record["media_id"])
        if media is None:
            raise AnalysisFailure("media_missing", "The imported video record no longer exists.")
        try:
            source = managed_path(media["source_relative_path"], must_exist=True)
        except FileNotFoundError as error:
            raise AnalysisFailure("source_missing", "The imported video is missing from the managed workspace.") from error
        if not source.is_file():
            raise AnalysisFailure("source_missing", "The imported video is missing from the managed workspace.")
        if source.stat().st_size != record["source_size_bytes"]:
            raise AnalysisFailure("source_changed", "The managed video changed after import. Re-import it before analysis.")
        metadata = probe_video(source)
        extension = source.suffix.lower()
        mime_type = MIME_BY_EXTENSION.get(extension) or mimetypes.guess_type(source.name)[0]
        if extension == ".mkv" or not mime_type or not mime_type.startswith("video/"):
            raise AnalysisFailure("unsupported_media", "Gemini does not support this imported video format.")
        candidates = _run_gemini(run_id, source, mime_type, metadata.duration_seconds)
        store_analysis_candidates(run_id, candidates)
        update_analysis_status(run_id, "completed", completed_at=utc_now(), error_code=None, error_message=None)
    except AnalysisFailure as error:
        update_analysis_status(
            run_id, "failed", completed_at=utc_now(), error_code=error.code, error_message=error.message,
        )
    except BaseException as error:
        code, message = _error_details(error)
        logger.error("Analysis run %s failed (%s): %s", run_id, type(error).__name__, message)
        update_analysis_status(run_id, "failed", completed_at=utc_now(), error_code=code, error_message=message)


def cleanup_interrupted_analysis(run_id: str) -> None:
    """Cancel stale server-side work and delete its temporary File API object after a restart."""
    if not settings.gemini_api_key:
        return
    record = get_analysis_run_record(run_id)
    if record is None or record["status"] != "interrupted":
        return
    file_name = record["remote_file_name"]
    interaction_id = record["remote_interaction_id"]
    if not file_name and not interaction_id:
        update_analysis_cleanup_state(run_id, cleanup_pending=False)
        return
    client = genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(
            api_version="v1beta",
            timeout=settings.gemini_timeout_seconds * 1000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    remaining_file = file_name
    remaining_interaction = interaction_id
    try:
        if interaction_id:
            try:
                current = client.interactions.get(id=interaction_id)
                if getattr(current, "status", None) == "in_progress":
                    client.interactions.cancel(id=interaction_id)
            except Exception:
                logger.warning("Gemini stale interaction cancellation is pending for analysis run %s", run_id)
            try:
                client.interactions.delete(id=interaction_id)
                remaining_interaction = ""
            except Exception:
                logger.warning("Gemini stale interaction record deletion is pending for analysis run %s", run_id)
        if file_name:
            try:
                client.files.delete(name=file_name)
                remaining_file = ""
            except Exception:
                logger.warning("Gemini stale file cleanup is pending for analysis run %s", run_id)
    finally:
        try:
            client.close()
        except Exception:
            logger.warning("Gemini cleanup client close failed for analysis run %s", run_id)
    pending = bool(remaining_file or remaining_interaction)
    update_analysis_cleanup_state(
        run_id,
        cleanup_pending=pending,
        remote_file_name=remaining_file,
        remote_interaction_id=remaining_interaction,
    )
