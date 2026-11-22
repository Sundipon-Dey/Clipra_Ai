"""Runtime paths and limits for the local application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPOSITORY_ROOT / "backend" / ".env")


@dataclass
class Settings:
    workspace_dir: Path
    max_upload_bytes: int
    max_files_per_import: int
    max_layout_image_bytes: int
    ffprobe_path: str | None
    ffmpeg_path: str | None
    ffprobe_timeout_seconds: int
    preview_timeout_seconds: int
    gemini_api_key: str
    gemini_model: str
    gemini_timeout_seconds: int
    gemini_file_max_bytes: int
    gemini_file_poll_timeout_seconds: int
    gemini_max_output_tokens: int
    gemini_interaction_timeout_seconds: int
    framing_extract_timeout_seconds: int
    framing_max_frame_bytes: int
    transcription_max_seconds: int
    transcription_timeout_seconds: int
    transcription_model: str
    youtube_client_secrets_file: Path

    @property
    def projects_dir(self) -> Path:
        return self.workspace_dir / "projects"

    @property
    def temp_dir(self) -> Path:
        return self.workspace_dir / "temp"

    @property
    def database_path(self) -> Path:
        return self.workspace_dir / "database" / "clipra.sqlite3"

    @property
    def transcription_models_dir(self) -> Path:
        return self.workspace_dir / "models" / "faster-whisper"

    def ensure_directories(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        root = self.workspace_dir.resolve(strict=True)
        for directory in (self.projects_dir, self.temp_dir, self.database_path.parent, self.transcription_models_dir):
            if not directory.resolve(strict=False).is_relative_to(root):
                raise RuntimeError("A CLIPRA storage directory resolves outside the configured workspace.")
            directory.mkdir(parents=True, exist_ok=True)
            if not directory.resolve(strict=True).is_relative_to(root):
                raise RuntimeError("A CLIPRA storage directory resolves outside the configured workspace.")


def _optional_tool(env_name: str) -> str | None:
    configured = os.getenv(env_name, "").strip()
    return configured or None


settings = Settings(
    workspace_dir=Path(os.getenv("CLIPRA_WORKSPACE_DIR") or str(REPOSITORY_ROOT)).expanduser().resolve(),
    max_upload_bytes=max(1, int(os.getenv("CLIPRA_MAX_UPLOAD_BYTES", str(20 * 1024**3)))),
    max_files_per_import=max(1, int(os.getenv("CLIPRA_MAX_FILES_PER_IMPORT", "20"))),
    max_layout_image_bytes=max(1024, int(os.getenv("CLIPRA_MAX_LAYOUT_IMAGE_BYTES", str(25 * 1024**2)))),
    ffprobe_path=_optional_tool("CLIPRA_FFPROBE"),
    ffmpeg_path=_optional_tool("CLIPRA_FFMPEG"),
    ffprobe_timeout_seconds=max(1, int(os.getenv("CLIPRA_FFPROBE_TIMEOUT_SECONDS", "45"))),
    preview_timeout_seconds=max(1, int(os.getenv("CLIPRA_PREVIEW_TIMEOUT_SECONDS", "3600"))),
    gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
    gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite",
    gemini_timeout_seconds=max(15, int(os.getenv("GEMINI_TIMEOUT_SECONDS", "300"))),
    gemini_file_max_bytes=max(1, int(os.getenv("GEMINI_FILE_MAX_BYTES", str(2 * 1024**3)))),
    gemini_file_poll_timeout_seconds=max(30, int(os.getenv("GEMINI_FILE_POLL_TIMEOUT_SECONDS", "600"))),
    gemini_max_output_tokens=max(256, int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "8192"))),
    gemini_interaction_timeout_seconds=max(60, int(os.getenv("GEMINI_INTERACTION_TIMEOUT_SECONDS", "1800"))),
    framing_extract_timeout_seconds=max(1, int(os.getenv("CLIPRA_FRAMING_EXTRACT_TIMEOUT_SECONDS", "60"))),
    framing_max_frame_bytes=max(64 * 1024, int(os.getenv("CLIPRA_FRAMING_MAX_FRAME_BYTES", str(3 * 1024**2)))),
    transcription_max_seconds=max(1, int(os.getenv("CLIPRA_TRANSCRIPTION_MAX_SECONDS", "900"))),
    transcription_timeout_seconds=max(60, int(os.getenv("CLIPRA_TRANSCRIPTION_TIMEOUT_SECONDS", "3600"))),
    transcription_model=os.getenv("CLIPRA_TRANSCRIPTION_MODEL", "small.en").strip() or "small.en",
    youtube_client_secrets_file=Path(os.getenv("YOUTUBE_CLIENT_SECRETS_FILE") or str(REPOSITORY_ROOT / "backend" / "secrets" / "youtube-oauth-client.json")).expanduser().resolve(),
)
