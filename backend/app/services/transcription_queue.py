"""Single local transcription worker with queued-run recovery."""

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from app.services.caption_store import queued_run_ids
from app.services.transcription_service import process_transcription

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipra-transcription")
_lock = Lock()
_scheduled: set[str] = set()


def enqueue_transcription(run_id: str) -> None:
    with _lock:
        if run_id in _scheduled:
            return
        _scheduled.add(run_id)
    def run() -> None:
        try:
            process_transcription(run_id)
        finally:
            with _lock:
                _scheduled.discard(run_id)
    _executor.submit(run)


def recover_queued_transcriptions() -> None:
    for run_id in queued_run_ids():
        enqueue_transcription(run_id)
