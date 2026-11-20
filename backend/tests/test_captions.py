from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.caption_grouping import group_words
from app.services.caption_store import create_run, get_run
from app.services.clip_store import create_clip
from app.services.project_store import get_media_record
from app.services.storage import managed_path
from app.services.transcription_service import process_transcription
from app.services.transcription_service import _extract_audio, TranscriptionFailure
from app.services.transcription_service import _words
from app.services.caption_store import update_run
from app.services.media_tools import resolve_ffmpeg, resolve_ffprobe
from conftest import generate_video


def _clip_with_audio(client, tmp_path: Path):
    video = generate_video(tmp_path / "spoken.mp4", duration=2.0, audio=True)
    project = client.post("/api/projects", json={"name": "Captions"}).json()
    with video.open("rb") as stream:
        media = client.post(f"/api/projects/{project['id']}/media", files={"files": (video.name, stream, "video/mp4")}).json()["imported"][0]
    record = get_media_record(media["id"])
    clip = create_clip(project_id=record["project_id"], media_id=record["id"], title="Caption clip", start=.2, end=1.6)
    return media, record, clip


def test_phrase_grouping_prefers_punctuation_pause_and_balanced_lines():
    words = [
        {"start_seconds": 0, "end_seconds": .2, "text": "I"},
        {"start_seconds": .2, "end_seconds": .4, "text": "cannot"},
        {"start_seconds": .4, "end_seconds": .6, "text": "believe"},
        {"start_seconds": .6, "end_seconds": .8, "text": "that"},
        {"start_seconds": .8, "end_seconds": 1, "text": "worked!"},
        {"start_seconds": 1.8, "end_seconds": 2, "text": "Really."},
    ]
    cues = group_words(words, {"max_words_per_line": 3, "max_lines": 2, "pause_seconds": .5})
    assert len(cues) == 2
    assert "\n" in cues[0]["generated_text"]
    assert cues[0]["generated_text"].replace("\n", " ") == "I cannot believe that worked!"
    assert cues[1]["generated_text"] == "Really."


def test_local_transcription_pipeline_uses_selected_audio_range_and_persists_track(client, tmp_path, monkeypatch):
    media, record, clip = _clip_with_audio(client, tmp_path)
    source = managed_path(record["source_relative_path"], must_exist=True)
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    model_dir = settings.transcription_models_dir / "base.en"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model.bin").write_bytes(b"fixture")
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    run_id = create_run(clip=clip, model_id="base.en", language="en", device_profile="cpu:int8")
    monkeypatch.setattr("app.services.transcription_service._words", lambda audio, run: [
        {"start_seconds": .0, "end_seconds": .2, "text": "Hello", "confidence": .9},
        {"start_seconds": .2, "end_seconds": .5, "text": "world!", "confidence": .9},
    ])
    process_transcription(run_id)
    run = get_run(run_id)
    assert run["status"] == "completed"
    track = client.get(f"/api/caption-tracks/{run['caption_track_id']}").json()
    assert track["segments"][0]["words"][0]["text"] == "Hello"
    assert not list((settings.temp_dir / "transcription").glob(f"{run_id}-*"))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == checksum
    model_dir.joinpath("model.bin").unlink(missing_ok=True)
    model_dir.joinpath("config.json").unlink(missing_ok=True)


def test_caption_api_preset_position_edit_reflow_and_stale_boundary(client, tmp_path):
    _, _, clip = _clip_with_audio(client, tmp_path)
    created = client.post(f"/api/clips/{clip['id']}/caption-tracks", json={"name": "Manual", "preset_id": "gaming_pulse"})
    assert created.status_code == 201
    track = created.json()
    assert track["style"]["animation"] == "pop_karaoke"
    moved = client.patch(f"/api/caption-tracks/{track['id']}", json={"position_x": .25, "position_y": .65}).json()
    assert moved["position_x"] == .25 and moved["position_y"] == .65
    changed = client.patch(f"/api/clips/{clip['id']}", json={"end_seconds": 1.4}).json()
    assert changed["end_seconds"] == 1.4
    assert client.get(f"/api/caption-tracks/{track['id']}").json()["stale"] is True
    assert client.patch(f"/api/caption-tracks/{track['id']}", json={"style": {"animation": "browser_sparkles"}}).status_code == 422


def test_hardware_and_model_endpoints_do_not_download_without_explicit_request(client, monkeypatch):
    monkeypatch.setattr("app.api.captions.hardware_profile", lambda: {"cpu_count": 8, "memory_gib": 16, "free_disk_gib": 20, "recommendation_model": "small.en", "explanation": "CPU recommendation."})
    profile = client.get("/api/transcription/hardware-profile")
    models = client.get("/api/transcription/models")
    assert profile.status_code == 200 and profile.json()["recommendation_model"] == "small.en"
    assert models.status_code == 200
    assert all(item["installed"] is False for item in models.json())


def test_explicit_ffmpeg_path_takes_priority(monkeypatch):
    monkeypatch.setattr(settings, "ffmpeg_path", r"C:\Tools With Spaces\ffmpeg.exe")
    monkeypatch.setattr("app.services.media_tools.shutil.which", lambda name: "PATH-" + name)
    assert resolve_ffmpeg() == r"C:\Tools With Spaces\ffmpeg.exe"


def test_ffmpeg_and_ffprobe_are_resolved_from_path_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "ffmpeg_path", None)
    monkeypatch.setattr(settings, "ffprobe_path", None)
    monkeypatch.setattr("app.services.media_tools.shutil.which", lambda name: rf"C:\ffmpeg\bin\{name}.EXE")
    assert resolve_ffmpeg() == r"C:\ffmpeg\bin\ffmpeg.EXE"
    assert resolve_ffprobe() == r"C:\ffmpeg\bin\ffprobe.EXE"


def test_missing_ffmpeg_has_setup_specific_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ffmpeg_path", None)
    monkeypatch.setattr("app.services.media_tools.shutil.which", lambda _name: None)
    with pytest.raises(TranscriptionFailure, match="Set CLIPRA_FFMPEG or add ffmpeg to PATH") as error:
        _extract_audio(tmp_path / "source.mp4", {"clip_start_seconds": 0, "clip_end_seconds": 1}, tmp_path)
    assert error.value.code == "ffmpeg_unavailable"


def test_audio_extraction_invokes_resolved_executable(tmp_path, monkeypatch):
    calls = []
    executable = r"C:\Tools With Spaces\ffmpeg.EXE"
    monkeypatch.setattr("app.services.transcription_service.resolve_ffmpeg", lambda: executable)

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        Path(command[-1]).write_bytes(b"RIFF-audio")

    monkeypatch.setattr("app.services.transcription_service.subprocess.run", fake_run)
    output = _extract_audio(tmp_path / "source file.mp4", {"clip_start_seconds": .25, "clip_end_seconds": 1.75}, tmp_path)
    assert output.is_file()
    assert calls[0][0][0] == executable
    assert calls[0][0][calls[0][0].index("-i") + 1] == str(tmp_path / "source file.mp4")


def test_installed_faster_whisper_and_pyav_versions_are_compatible():
    from importlib.metadata import version
    assert version("faster-whisper") == "1.2.1"
    assert version("av") == "18.0.0"
    from faster_whisper.audio import decode_audio
    audio = Path(__file__).parent / "fixtures" / "compat.wav"
    audio.parent.mkdir(exist_ok=True)
    import wave
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000); wav.writeframes(bytes(3200))
    try:
        assert len(decode_audio(str(audio))) > 0
    finally:
        audio.unlink(missing_ok=True)


def test_metadata_errors_typeerror_is_classified_as_audio_decode_compatibility(tmp_path, monkeypatch):
    class BrokenModel:
        def transcribe(self, *args, **kwargs):
            raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")
    monkeypatch.setattr("app.services.transcription_service._model", lambda _run: BrokenModel())
    with pytest.raises(TranscriptionFailure) as caught:
        _words(tmp_path / "clip.wav", {"model_id":"small.en", "device_profile":"cpu:int8", "language":"en", "clip_start_seconds":0, "clip_end_seconds":2})
    assert caught.value.code == "audio_decode_incompatible"
    assert "PyAV version is incompatible" in caught.value.message


def test_failure_message_is_persisted_and_retrievable(client, tmp_path):
    _, _, clip = _clip_with_audio(client, tmp_path)
    run_id = create_run(clip=clip, model_id="small.en", language="en", device_profile="cuda:float16")
    update_run(run_id, "failed", error_code="audio_decode_incompatible", error_message="Decoder incompatibility. Reinstall pinned dependencies.", completed=True)
    result = client.get(f"/api/transcriptions/{run_id}")
    assert result.status_code == 200
    assert result.json()["error_code"] == "audio_decode_incompatible"
    assert result.json()["error_message"] == "Decoder incompatibility. Reinstall pinned dependencies."


def test_transcription_endpoint_accepts_explicit_clip_boundaries(client, tmp_path, monkeypatch):
    _, _, clip = _clip_with_audio(client, tmp_path)
    monkeypatch.setattr("app.api.captions.installed", lambda _model: True)
    monkeypatch.setattr("app.api.captions.enqueue_transcription", lambda _run: None)
    response = client.post(f"/api/clips/{clip['id']}/transcriptions", json={"model_id":"small.en", "language":"en", "start_seconds":.75, "end_seconds":1.25})
    assert response.status_code == 202
    assert response.json()["device_profile"] == "cpu:int8"
    assert response.json()["clip_start_seconds"] == .75
    assert response.json()["clip_end_seconds"] == 1.25

