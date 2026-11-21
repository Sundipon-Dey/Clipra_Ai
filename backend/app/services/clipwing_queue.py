"""Metadata lookup and per-suggestion Clipwing download workers."""
from __future__ import annotations

import copy
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.services.clipwing_imports import (
    get_entry, get_import, queued_import_ids, register_cut, set_entry,
    set_job, set_video_metadata,
)
from app.services.media_validation import probe_video
from app.services.project_store import get_project
from app.services.storage import managed_directory, relative_path

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipra-clipwing")
_lock = threading.Lock()
_scheduled: set[str] = set()
_metadata_cache: dict[str, dict] = {}
_FORMAT_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def _schedule(key: str, callback) -> None:
    with _lock:
        if key in _scheduled:
            return
        _scheduled.add(key)

    def run() -> None:
        try:
            callback()
        finally:
            with _lock:
                _scheduled.discard(key)
    _executor.submit(run)


def enqueue_lookup(import_id: str) -> None:
    _schedule(f"lookup:{import_id}", lambda: lookup_video(import_id))


def enqueue_download(import_id: str, entry_id: str, format_id: str) -> None:
    _schedule(f"download:{entry_id}", lambda: download_entry(import_id, entry_id, format_id))


def invalidate_metadata(import_id: str) -> None:
    with _lock:
        _metadata_cache.pop(import_id, None)


def _youtube_dl():
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError("YouTube import support is missing. Install backend requirements and restart the API.") from exc
    return YoutubeDL


def _codec_name(value: str | None) -> str:
    name = (value or "").lower()
    if name.startswith(("avc", "h264")):
        return "H.264"
    if name.startswith(("av01", "av1")):
        return "AV1"
    if name.startswith(("vp09", "vp9")):
        return "VP9"
    if name.startswith(("hev1", "hvc1", "hevc")):
        return "HEVC"
    if name.startswith(("mp4a", "aac")):
        return "AAC"
    if name.startswith("opus"):
        return "Opus"
    if name.startswith("none"):
        return ""
    return (value or "Unknown").split(".")[0][:24]


def _format_choices(info: dict) -> list[dict]:
    choices: list[dict] = []
    for fmt in info.get("formats") or []:
        format_id = str(fmt.get("format_id") or "")
        height = fmt.get("height")
        vcodec = str(fmt.get("vcodec") or "")
        if not _FORMAT_ID.fullmatch(format_id) or not isinstance(height, int) or height < 144 or height > 2160 or not vcodec or vcodec == "none":
            continue
        ext = str(fmt.get("ext") or "unknown").lower()
        audio = _codec_name(fmt.get("acodec")) or "separate audio"
        video = _codec_name(vcodec)
        width = fmt.get("width") if isinstance(fmt.get("width"), int) else None
        fps = fmt.get("fps") if isinstance(fmt.get("fps"), (int, float)) else None
        size = fmt.get("filesize") or fmt.get("filesize_approx")
        label = f"{height}p · {ext.upper()} · {video} · {audio}"
        if fps:
            label += f" · {fps:g} fps"
        choices.append({
            "format_id": format_id,
            "label": label,
            "width": width,
            "height": height,
            "ext": ext,
            "video_codec": video,
            "audio_codec": _codec_name(fmt.get("acodec")) or None,
            "fps": fps,
            "filesize_bytes": int(size) if isinstance(size, (int, float)) and size > 0 else None,
        })
    choices.sort(key=lambda item: (item["height"], item["fps"] or 0, item["ext"] == "mp4"), reverse=True)
    return choices[:80]


def _extract_info(url: str) -> dict:
    YoutubeDL = _youtube_dl()
    ffmpeg = shutil.which(settings.ffmpeg_path or "ffmpeg")
    options = {
        "quiet": True,
        "no_warnings": True,
        "no_color": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 2,
        "fragment_retries": 2,
        "ffmpeg_location": str(Path(ffmpeg).parent) if ffmpeg else None,
    }
    try:
        with YoutubeDL({key: value for key, value in options.items() if value is not None}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise RuntimeError("YouTube could not provide video details. It may be unavailable, private, region-restricted, or unsupported.") from exc
    if not isinstance(info, dict) or not info.get("formats"):
        raise RuntimeError("YouTube returned no selectable video formats.")
    return info


def _cache_info(import_id: str, info: dict) -> None:
    with _lock:
        _metadata_cache[import_id] = info
        while len(_metadata_cache) > 20:
            _metadata_cache.pop(next(iter(_metadata_cache)))


def lookup_video(import_id: str) -> None:
    job = get_import(import_id)
    if not job or job["status"] != "queued":
        return
    set_job(import_id, status="downloading", stage="Checking available video formats", progress=.1)
    try:
        info = _extract_info(job["video_url"])
        choices = _format_choices(info)
        if not choices:
            raise RuntimeError("No downloadable video formats at or below 2160p were found.")
        _cache_info(import_id, info)
        set_video_metadata(
            import_id,
            title=str(info.get("title") or "YouTube video"),
            duration_seconds=float(info["duration"]) if info.get("duration") else None,
            formats=choices,
        )
        if info.get("duration"):
            for item in job["entries"]:
                if item["end_seconds"] > float(info["duration"]) + .1:
                    set_entry(item["id"], status="failed", error_message=f"This timestamp exceeds the video duration ({float(info['duration']):.1f} seconds).")
        set_job(import_id, status="completed", stage="Video details ready - choose a format for each clip", progress=1)
    except Exception as exc:
        message = str(exc)[:1000] or "Video details could not be loaded."
        set_job(import_id, status="failed", stage="Video details lookup failed", progress=1, error_message=message)
        for item in job["entries"]:
            if item["status"] == "queued":
                set_entry(item["id"], status="failed", error_message=message)


def _selected_format_selector(info: dict, format_id: str) -> str:
    formats = info.get("formats") or []
    selected = next((item for item in formats if str(item.get("format_id")) == format_id), None)
    if selected is None:
        raise RuntimeError("This format is no longer available. Refresh video details before downloading.")
    if selected.get("acodec") and selected["acodec"] != "none":
        return format_id
    audios = [item for item in formats if item.get("acodec") and item["acodec"] != "none" and (not item.get("vcodec") or item["vcodec"] == "none")]
    if not audios:
        return format_id
    audios.sort(key=lambda item: (item.get("ext") == "m4a", item.get("abr") or 0, item.get("filesize") or 0), reverse=True)
    return f"{format_id}+{audios[0]['format_id']}"


def _download_options(import_id: str, entry_id: str, item: dict, format_id: str, temp_dir: Path, info: dict) -> dict:
    ffmpeg = shutil.which(settings.ffmpeg_path or "ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for precise section downloads. Set CLIPRA_FFMPEG and restart.")
    start, end = float(item["start_seconds"]), float(item["end_seconds"])
    selected_source = next((value for value in info.get("formats") or [] if str(value.get("format_id")) == format_id), {})
    format_selector = _selected_format_selector(info, format_id)
    last_progress = [0.0]

    def progress_hook(event: dict) -> None:
        status = event.get("status")
        if status == "downloading":
            total = event.get("total_bytes") or event.get("total_bytes_estimate")
            downloaded = int(event.get("downloaded_bytes") or 0)
            if downloaded > settings.max_upload_bytes or (total and total > settings.max_upload_bytes):
                raise RuntimeError("This selected clip exceeds CLIPRA's configured file-size limit.")
            progress = min(.84, .84 * downloaded / total) if total else min(.7, last_progress[0] + .005)
        elif status == "finished":
            progress = .86
        else:
            return
        last_progress[0] = max(last_progress[0], progress)
        set_entry(entry_id, status="cutting", progress=last_progress[0])

    def postprocessor_hook(event: dict) -> None:
        progress = .9 if event.get("status") == "started" else .98
        last_progress[0] = max(last_progress[0], progress)
        set_entry(entry_id, status="cutting", progress=last_progress[0])

    options = {
        "format": format_selector,
        "outtmpl": str(temp_dir / "clip.%(ext)s"),
        "merge_output_format": "mp4",
        "recodevideo": "mp4",
        "download_ranges": lambda _info, _ydl: [{"start_time": start, "end_time": end}],
        "force_keyframes_at_cuts": True,
        "ffmpeg_location": str(Path(ffmpeg).parent),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "no_color": True,
        "continuedl": False,
        "overwrites": False,
        "socket_timeout": 30,
        "retries": 2,
        "fragment_retries": 2,
        "max_filesize": settings.max_upload_bytes,
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
        "postprocessor_args": {"ffmpeg": ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k"]},
    }
    if selected_source.get("ext") == "mp4" or "+" in format_selector:
        options["external_downloader_args"] = {
            "ffmpeg_o1": ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k"],
        }
    return options


def _download_section(import_id: str, entry_id: str, item: dict, format_id: str, info: dict, temp_dir: Path) -> Path:
    YoutubeDL = _youtube_dl()
    options = _download_options(import_id, entry_id, item, format_id, temp_dir, info)
    try:
        with YoutubeDL(options) as ydl:
            ydl.process_ie_result(copy.deepcopy(info), download=True)
    except Exception as exc:
        if "file-size limit" in str(exc).lower():
            raise RuntimeError("This selected clip exceeds CLIPRA's configured file-size limit.") from exc
        raise RuntimeError("The selected video segment could not be downloaded and recompressed. Try another format or refresh the video details.") from exc
    outputs = [path for path in temp_dir.glob("clip.*") if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"} and not path.name.endswith(".part")]
    if not outputs:
        raise RuntimeError("The segment download finished without a usable video file.")
    output = max(outputs, key=lambda path: path.stat().st_size)
    if output.stat().st_size > settings.max_upload_bytes:
        raise RuntimeError("This selected clip exceeds CLIPRA's configured file-size limit.")
    return output


def download_entry(import_id: str, entry_id: str, format_id: str) -> None:
    job = get_import(import_id)
    item = get_entry(entry_id)
    if not job or not item or item["import_id"] != import_id or item["status"] != "cutting":
        return
    project = get_project(job["project_id"])
    if not project:
        set_entry(entry_id, status="failed", error_message="The project no longer exists.")
        return
    try:
        with _lock:
            info = _metadata_cache.get(import_id)
        if info is None:
            # Metadata URLs are intentionally kept in memory only; a restart can require a fresh lookup.
            info = _extract_info(job["video_url"])
            _cache_info(import_id, info)
        temp_dir = managed_directory(f"temp/clipwing/{import_id}/{entry_id}")
        output = _download_section(import_id, entry_id, item, format_id, info, temp_dir)
        metadata = probe_video(output)
        media_id, clip_id = str(uuid4()), str(uuid4())
        project_dir = managed_directory(f"projects/{project.id}/sources")
        final_path = project_dir / f"{media_id}.mp4"
        output.replace(final_path)
        try:
            filename = f"Clipwing - {item['title'][:140]}.mp4"
            register_cut(
                entry_id=entry_id,
                project_id=project.id,
                media_id=media_id,
                clip_id=clip_id,
                filename=filename,
                relative_source_path=relative_path(final_path),
                size_bytes=final_path.stat().st_size,
                metadata=metadata,
            )
        except Exception:
            final_path.unlink(missing_ok=True)
            raise
    except Exception as exc:
        invalidate_metadata(import_id)
        set_entry(entry_id, status="failed", progress=0, error_message=str(exc)[:1000] or "This clip could not be downloaded.")
    finally:
        root = settings.temp_dir.resolve(strict=True)
        resolved = settings.temp_dir.joinpath("clipwing", import_id, entry_id).resolve(strict=False)
        if resolved.is_relative_to(root) and resolved != root:
            shutil.rmtree(resolved, ignore_errors=True)


def recover_queued_imports() -> None:
    from app.services.clipwing_imports import interrupt_active_imports
    interrupt_active_imports()
    for import_id in queued_import_ids():
        enqueue_lookup(import_id)
