"""Real local faster-whisper clip transcription with managed temporary audio."""

from __future__ import annotations

import logging
import math
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from faster_whisper import WhisperModel

from app.core.config import settings
from app.services.caption_store import create_track_from_words, get_run, update_run
from app.services.clip_store import get_clip
from app.services.project_store import get_media_record
from app.services.media_tools import resolve_ffmpeg
from app.services.storage import StoragePathError, managed_directory, managed_path
from app.services.transcription_models import installed, model_path

logger = logging.getLogger(__name__)
_models: dict[tuple[str, str, str], WhisperModel] = {}


class TranscriptionFailure(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _extract_audio(source: Path, run: dict, directory: Path) -> Path:
    tool = resolve_ffmpeg()
    if not tool:
        raise TranscriptionFailure("ffmpeg_unavailable", "FFmpeg was not found. Set CLIPRA_FFMPEG or add ffmpeg to PATH, then restart CLIPRA.AI.")
    output = directory / "clip-audio.wav"
    duration = run["clip_end_seconds"] - run["clip_start_seconds"]
    command = [tool, "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", f"{run['clip_start_seconds']:.3f}", "-t", f"{duration:.3f}", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-y", str(output)]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=settings.transcription_timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise TranscriptionFailure("audio_extraction_timeout", "Audio extraction timed out. The source video was not changed.") from exc
    except FileNotFoundError as exc:
        raise TranscriptionFailure("ffmpeg_unavailable", "The configured FFmpeg executable could not be started. Check CLIPRA_FFMPEG or PATH and restart CLIPRA.AI.") from exc
    except subprocess.CalledProcessError as exc:
        logger.info("FFmpeg audio extraction failed with exit code %s", exc.returncode)
        raise TranscriptionFailure("audio_extraction_failed", "FFmpeg ran but could not extract audio from this source. Verify the video has a readable audio stream and supported codecs.") from exc
    except OSError as exc:
        raise TranscriptionFailure("audio_extraction_failed", "The selected clip audio could not be extracted. Verify the source has a supported audio stream.") from exc
    if not output.is_file() or output.stat().st_size == 0:
        raise TranscriptionFailure("audio_missing", "The selected clip did not produce usable audio.")
    return output


def _model(run: dict) -> WhisperModel:
    if not installed(run["model_id"]):
        raise TranscriptionFailure("model_not_installed", "The selected local transcription model is not installed. Download it explicitly before transcription.")
    device, compute_type = "cpu", "int8"
    key = (run["model_id"], device, compute_type)
    if key not in _models:
        try:
            _models[key] = WhisperModel(str(model_path(run["model_id"])), device=device, compute_type=compute_type, local_files_only=True)
        except Exception as exc:
            logger.exception("Transcription model initialization failed (%s)", type(exc).__name__)
            raise TranscriptionFailure("model_load_failed", "The local transcription model could not be loaded with this hardware profile.") from exc
    return _models[key]


def _words(audio: Path, run: dict) -> list[dict]:
    model = _model(run)
    try:
        segments, _ = model.transcribe(str(audio), language=run["language"], task="transcribe", beam_size=5, word_timestamps=True, vad_filter=True, condition_on_previous_text=False)
        words: list[dict] = []
        for segment in segments:
            for word in segment.words or []:
                start, end, text = word.start, word.end, (word.word or "").strip()
                if not text or not all(isinstance(item, (int, float)) and math.isfinite(item) for item in (start, end)):
                    continue
                if start < 0 or end < start or end > run["clip_end_seconds"] - run["clip_start_seconds"] + 0.05:
                    continue
                words.append({"start_seconds": round(float(start), 3), "end_seconds": round(float(end), 3), "text": text, "confidence": None})
    except TranscriptionFailure:
        raise
    except TypeError as exc:
        if "metadata_errors" in str(exc):
            logger.exception("Audio decoding failed due to faster-whisper/PyAV incompatibility (%s)", type(exc).__name__)
            raise TranscriptionFailure("audio_decode_incompatible", "Audio decoding failed because the installed PyAV version is incompatible with faster-whisper. Reinstall the pinned backend dependencies.") from exc
        logger.exception("Transcription inference failed (%s)", type(exc).__name__)
        raise TranscriptionFailure("inference_failed", "Transcription inference failed. Check the model and hardware configuration.") from exc
    except Exception as exc:
        logger.exception("Audio decoding or transcription inference failed (%s)", type(exc).__name__)
        raise TranscriptionFailure("inference_failed", "Audio decoding or transcription inference failed. Check the selected model and hardware configuration.") from exc
    if not words:
        raise TranscriptionFailure("no_speech_detected", "No transcribable speech was detected in the selected clip.")
    last = -1.0
    for word in words:
        if word["start_seconds"] < last:
            raise TranscriptionFailure("invalid_timestamps", "The local transcription returned unusable word timing.")
        last = word["end_seconds"]
    return words


def process_transcription(run_id: str) -> None:
    run = get_run(run_id)
    temp = None
    try:
        if run is None or run["status"] != "queued":
            return
        clip = get_clip(run["clip_id"])
        media = get_media_record(run["media_id"])
        if clip is None or media is None:
            raise TranscriptionFailure("source_missing", "The draft clip or imported source no longer exists.")
        if not media["has_audio"]:
            raise TranscriptionFailure("no_audio_stream", "This source video has no audio stream to transcribe.")
        if run["clip_end_seconds"] - run["clip_start_seconds"] > settings.transcription_max_seconds:
            raise TranscriptionFailure("clip_too_long", f"The selected clip exceeds the configured local transcription limit of {settings.transcription_max_seconds} seconds.")
        try:
            source = managed_path(media["source_relative_path"], must_exist=True)
        except (FileNotFoundError, StoragePathError, ValueError) as exc:
            raise TranscriptionFailure("source_missing", "The managed source video is missing or failed a storage security check.") from exc
        temp = managed_directory(f"temp/transcription/{run_id}-{uuid4().hex}")
        update_run(run_id, "extracting", started=True)
        audio = _extract_audio(source, run, temp)
        update_run(run_id, "transcribing")
        words = _words(audio, run)
        try:
            create_track_from_words(run=run, words=words)
        except Exception as exc:
            logger.exception("Transcription result persistence failed (%s)", type(exc).__name__)
            raise TranscriptionFailure("result_persistence_failed", "Transcription completed, but its caption results could not be saved.") from exc
        update_run(run_id, "completed", completed=True)
    except TranscriptionFailure as exc:
        update_run(run_id, "failed", error_code=exc.code, error_message=exc.message, completed=True)
    except Exception as exc:
        logger.exception("Unexpected transcription job failure (%s)", type(exc).__name__)
        update_run(run_id, "failed", error_code="transcription_internal_error", error_message="An unexpected local transcription error occurred. See sanitized backend logs for diagnostic details.", completed=True)
    finally:
        if temp is not None and temp.resolve(strict=False).is_relative_to(settings.temp_dir.resolve(strict=True)):
            shutil.rmtree(temp, ignore_errors=True)
