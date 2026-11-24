"""FastAPI entry point for the local CLIPRA.AI backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.media import router as media_router
from app.api.clipwing import router as clipwing_router
from app.api.clips import router as clips_router
from app.api.captions import router as captions_router
from app.api.projects import router as projects_router
from app.api.renders import router as renders_router
from app.api.layout_images import router as layout_images_router
from app.api.social_content import router as social_content_router
from app.api.youtube import router as youtube_router
from app.api.facebook import router as facebook_router
from app.api.instagram import router as instagram_router
from app.core.config import settings
from app.db.database import initialize_database
from app.services.clipwing_queue import recover_queued_imports
from app.services.analysis_queue import recover_queued_analyses
from app.services.project_store import interrupt_legacy_gemini_runs
from app.services.transcription_queue import recover_queued_transcriptions
from app.services.render_queue import recover_queued_renders
from app.services.social_content_queue import recover_social_generations
from app.services.youtube_upload_store import interrupt_active as interrupt_youtube_uploads
from app.services.facebook_upload_store import interrupt_active as interrupt_facebook_uploads
from app.services.instagram_upload_store import interrupt_active as interrupt_instagram_uploads


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_directories()
    initialize_database()
    recover_queued_imports()
    interrupt_legacy_gemini_runs()
    recover_queued_analyses()
    recover_queued_transcriptions()
    recover_queued_renders()
    recover_social_generations()
    interrupt_youtube_uploads()
    interrupt_facebook_uploads()
    interrupt_instagram_uploads()
    yield


app = FastAPI(
    title="CLIPRA.AI API",
    version="0.4.0",
    description="Local CLIPRA media importing, Clipwing clip extraction, editing, and captions.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "HEAD", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Return a real response from the running backend process."""
    return {
        "status": "ok",
        "service": "clipra-api",
        "version": app.version,
        "max_upload_bytes": str(settings.max_upload_bytes),
        "max_files_per_import": str(settings.max_files_per_import),
        "gemini_configured": "true" if bool(settings.gemini_api_key) else "false",
        "gemini_model": settings.gemini_model,
        "gemini_file_max_bytes": str(settings.gemini_file_max_bytes),
    }


app.include_router(projects_router)
app.include_router(media_router)
app.include_router(clipwing_router)
app.include_router(clips_router)
app.include_router(captions_router)
app.include_router(renders_router)
app.include_router(layout_images_router)
app.include_router(social_content_router)
app.include_router(youtube_router)
app.include_router(facebook_router)
app.include_router(instagram_router)
