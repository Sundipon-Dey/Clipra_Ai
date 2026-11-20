"""In-process single-worker queue; state is persisted so restart is visible."""

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from app.services.clip_store import fail_framing
from app.services.framing_analysis import process_framing

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipra-framing")
_lock = Lock()
_scheduled: set[str] = set()


def enqueue_framing(clip_id: str) -> None:
    with _lock:
        if clip_id in _scheduled:
            return
        _scheduled.add(clip_id)

    def run() -> None:
        try:
            process_framing(clip_id)
        finally:
            with _lock:
                _scheduled.discard(clip_id)

    try:
        _executor.submit(run)
    except RuntimeError:
        with _lock:
            _scheduled.discard(clip_id)
        fail_framing(clip_id, code="queue_unavailable", message="The local framing worker is unavailable. Manual framing remains available.")
