"""FastAPI entry point for the local CLIPRA.AI backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.media import router as media_router
from app.api.analyses import router as analyses_router
from app.api.clips import router as clips_router
from app.api.captions import router as captions_router
from app.api.projects import router as projects_router
from app.api.renders import router as renders_router
from app.api.layout_images import router as layout_images_router
from app.core.config import settings
from app.db.database import initialize_database
from app.services.analysis_queue import recover_queued_analyses
from app.services.transcription_queue import recover_queued_transcriptions
from app.services.render_queue import recover_queued_renders


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_directories()
    initialize_database()
    recover_queued_analyses()
    recover_queued_transcriptions()
    recover_queued_renders()
    yield


app = FastAPI(
    title="CLIPRA.AI API",
    version="0.4.0",
    description="Local CLIPRA media, highlight analysis, clip editing, and local captions.",
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
app.include_router(analyses_router)
app.include_router(clips_router)
app.include_router(captions_router)
app.include_router(renders_router)
app.include_router(layout_images_router)
