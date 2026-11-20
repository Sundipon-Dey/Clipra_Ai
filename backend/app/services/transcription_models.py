"""Explicit local faster-whisper model downloads and model availability."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from huggingface_hub import snapshot_download

from app.core.config import settings
from app.services.storage import managed_directory

MODEL_CATALOG = {
    "base.en": {"display_name": "Base English", "repo_id": "Systran/faster-whisper-base.en", "language": "en", "estimated_download_mb": 145},
    "small.en": {"display_name": "Small English", "repo_id": "Systran/faster-whisper-small.en", "language": "en", "estimated_download_mb": 465},
    "small": {"display_name": "Small Multilingual", "repo_id": "Systran/faster-whisper-small", "language": "multilingual", "estimated_download_mb": 465},
}
_downloads: dict[str, dict] = {}
_lock = Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipra-model-download")


def model_path(model_id: str):
    if model_id not in MODEL_CATALOG:
        raise ValueError("Unsupported transcription model.")
    return settings.transcription_models_dir / model_id


def installed(model_id: str) -> bool:
    path = model_path(model_id)
    return (path / "model.bin").is_file() and (path / "config.json").is_file()


def list_models(recommended: str) -> list[dict]:
    return [{"id": model_id, "display_name": data["display_name"], "language": data["language"], "estimated_download_mb": data["estimated_download_mb"], "installed": installed(model_id), "recommended": model_id == recommended} for model_id, data in MODEL_CATALOG.items()]


def download_status(model_id: str) -> dict:
    if model_id not in MODEL_CATALOG:
        raise ValueError("Unsupported transcription model.")
    with _lock:
        current = dict(_downloads.get(model_id, {}))
    if installed(model_id):
        return {"id": model_id, "status": "installed", "error_message": None}
    return {"id": model_id, "status": current.get("status", "not_downloaded"), "error_message": current.get("error_message")}


def begin_download(model_id: str) -> dict:
    if model_id not in MODEL_CATALOG:
        raise ValueError("Unsupported transcription model.")
    if installed(model_id):
        return download_status(model_id)
    with _lock:
        if _downloads.get(model_id, {}).get("status") == "downloading":
            return download_status(model_id)
        _downloads[model_id] = {"status": "downloading", "error_message": None}

    def work() -> None:
        try:
            target = managed_directory(f"models/faster-whisper/{model_id}")
            snapshot_download(repo_id=MODEL_CATALOG[model_id]["repo_id"], local_dir=str(target))
            with _lock:
                _downloads[model_id] = {"status": "installed", "error_message": None}
        except Exception:
            with _lock:
                _downloads[model_id] = {"status": "failed", "error_message": "The local model download failed. Check your connection and available disk space, then try again."}

    _executor.submit(work)
    return download_status(model_id)
