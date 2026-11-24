"""Single-worker executor for explicit Instagram Reels publications."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.services import instagram_upload_service

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipra-instagram-upload")


def enqueue(upload_id: str, video_path: Path, package: dict, instagram_user_id: str) -> None:
    _executor.submit(instagram_upload_service.run, upload_id, video_path, package, instagram_user_id)
