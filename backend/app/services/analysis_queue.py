"""Single-worker persistent analysis queue backed by SQLite run records."""

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from app.services.highlight_analysis import cleanup_interrupted_analysis, process_analysis
from app.services.project_store import list_interrupted_cleanup_records, list_queued_analysis_ids


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipra-analysis")
_lock = Lock()
_scheduled: set[str] = set()


def enqueue_analysis(run_id: str) -> None:
    with _lock:
        if run_id in _scheduled:
            return
        _scheduled.add(run_id)

    def run() -> None:
        try:
            process_analysis(run_id)
        finally:
            with _lock:
                _scheduled.discard(run_id)

    _executor.submit(run)


def recover_queued_analyses() -> None:
    """Clean up stale Google jobs first, then resume queued runs without a request sent."""
    for record in list_interrupted_cleanup_records():
        run_id = record["id"]
        with _lock:
            if run_id in _scheduled:
                continue
            _scheduled.add(run_id)

        def cleanup(target_id: str = run_id) -> None:
            try:
                cleanup_interrupted_analysis(target_id)
            finally:
                with _lock:
                    _scheduled.discard(target_id)

        _executor.submit(cleanup)
    for run_id in list_queued_analysis_ids():
        enqueue_analysis(run_id)
