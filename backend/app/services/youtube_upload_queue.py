"""Single-worker executor for long YouTube uploads."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.services import youtube_upload_service

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipra-youtube-upload")


def enqueue(upload_id: str, video_path: Path, package: dict) -> None:
    _executor.submit(youtube_upload_service.run, upload_id, video_path, package)
