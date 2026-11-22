"""Single durable worker for consented Stage 6 Gemini requests."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from app.services import social_content_store
from app.services.social_content_service import cleanup_pending_remote, process_generation

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipra-social")


def enqueue(generation_id: str) -> None:
    _executor.submit(process_generation, generation_id)


def recover_social_generations() -> None:
    queued, cleanup = social_content_store.recovery_state()
    for generation_id in cleanup:
        try:
            cleanup_pending_remote(generation_id)
        except Exception:
            logger.warning("Remote cleanup remains pending for interrupted social generation %s", generation_id)
    for generation_id in queued:
        enqueue(generation_id)
