"""Single-worker executor for explicit Facebook Reels uploads."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.services import facebook_upload_service

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipra-facebook-upload")


def enqueue(upload_id: str, video_path: Path, package: dict, page_id: str) -> None:
    _executor.submit(facebook_upload_service.run, upload_id, video_path, package, page_id)
