"""Single local render worker; queued jobs resume, active jobs become interrupted."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.services.render_pipeline import render
from app.services.render_store import fail, finish, get, set_progress, start
from app.services.storage import managed_directory, relative_path

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipra-render")


def enqueue(job_id: str) -> None:
    _executor.submit(_run, job_id)


def _run(job_id: str) -> None:
    job = get(job_id)
    if not job or job["status"] != "queued":
        return
    start(job_id)
    job = get(job_id)
    try:
        import json
        snapshot = json.loads(job["snapshot_json"])
        if job["kind"] == "preview":
            directory = managed_directory(f"projects/{job['project_id']}/previews/clips/{job['clip_id']}")
            filename = f"preview-{job_id}.mp4"
        else:
            directory = managed_directory(f"projects/{job['project_id']}/exports/{job['clip_id']}")
            filename = f"V{int(job['version_number']):03d}-{job_id}.mp4"
        output = directory / filename
        render(snapshot, output, preview=job["kind"] == "preview", job_id=job_id,
               progress_callback=lambda progress: set_progress(job_id, progress, "encoding"))
        finish(job_id, relative=relative_path(output), size=output.stat().st_size)
    except Exception as exc:
        fail(job_id, str(exc) or "The render failed.")


def recover_queued_renders() -> None:
    from app.services.render_store import recover
    for job_id in recover():
        enqueue(job_id)

