"""Parsing and persistence for user-pasted Clipwing analysis imports."""
from __future__ import annotations

import re
import json
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from app.db.database import connect
from app.services.project_store import utc_now

_TIME = r"\d{1,3}:\d{2}(?::\d{2})?(?:\.\d+)?"
_HEADER = re.compile(rf"\((?P<start>{_TIME})\s*[\u2010-\u2015\u2212-]\s*(?P<end>{_TIME})(?:\s*,\s*score\s*(?P<score>\d{{1,3}}(?:\.\d+)?))?\s*\)", re.I)
_LINK = re.compile(r"https?://[^\s<>\]\[()\"']+", re.I)
_BLOCK = re.compile(r"(?=^\s*\d+[.)]\s+)", re.M)


def _seconds(value: str) -> float:
    parts = [float(part) for part in value.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def youtube_video_url(value: str) -> str:
    value = value.strip().rstrip(".,;:!?)\"'")
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    video_id = ""
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "youtube-nocookie.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        else:
            match = re.match(r"/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})(?:/|$)", parsed.path)
            video_id = match.group(1) if match else ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Paste a standard YouTube watch or youtu.be URL for every analysis entry.")
    return f"https://www.youtube.com/watch?v={video_id}"


def parse_clipwing_text(text: str) -> tuple[str, list[dict]]:
    clean = text.replace("\\\n", "\n").replace("&#x20;", " ").strip()
    if not clean:
        raise ValueError("Paste Clipwing's analysis text first.")
    starts = [match.start() for match in _BLOCK.finditer(clean)]
    raw_blocks = [clean[start:end].strip() for start, end in zip(starts, starts[1:] + [len(clean)]) if clean[start:end].strip()] if starts else [clean]
    if len(raw_blocks) > 40:
        raise ValueError("One import can contain at most 40 clip suggestions.")
    global_links = [youtube_video_url(match.group(0)) for match in _LINK.finditer(clean)]
    entries: list[dict] = []
    for ordinal, block in enumerate(raw_blocks):
        block_lines = block.splitlines()
        if not block_lines:
            raise ValueError(f"Entry {ordinal + 1} is blank. Remove empty numbered entries and try again.")
        header = block_lines[0].strip().rstrip("\\")
        timing = _HEADER.search(header)
        if not timing:
            raise ValueError(f"Entry {ordinal + 1} needs a title and timestamps like 0:53-2:06 with a score.")
        start, end = _seconds(timing.group("start")), _seconds(timing.group("end"))
        score = float(timing.group("score")) if timing.group("score") is not None else None
        if start < 0 or end <= start or end - start > 1800 or (score is not None and score > 100):
            raise ValueError(f"Entry {ordinal + 1} has an invalid time range or score.")
        title = header[:timing.start()].strip()
        title = re.sub(r"^\s*\d+[.)]\s*", "", title).strip(" \t-\u2010\u2011\u2012\u2013\u2014\u2015")
        if not title or len(title) > 160:
            raise ValueError(f"Entry {ordinal + 1} needs a title between 1 and 160 characters.")
        links = [youtube_video_url(match.group(0)) for match in _LINK.finditer(block)]
        video_url = links[0] if links else (global_links[0] if global_links else None)
        if not video_url:
            raise ValueError(f"Entry {ordinal + 1} is missing its YouTube video link.")
        if any(link != video_url for link in links):
            raise ValueError("Each entry must refer to the same YouTube video.")
        quote = re.search(r"[\"\u201c](.*?)[\"\u201d]", block, re.S)
        transcript = re.sub(r"\s+", " ", quote.group(1)).strip()[:5000] if quote else None
        entries.append({"ordinal": ordinal, "title": title, "start_seconds": start, "end_seconds": end, "score": score, "transcript": transcript, "video_url": video_url})
    if not entries:
        raise ValueError("No numbered Clipwing entries were found.")
    urls = {entry["video_url"] for entry in entries}
    if len(urls) != 1:
        raise ValueError("Paste suggestions from one YouTube video per import.")
    return urls.pop(), entries


def create_import(*, project_id: str, analysis_text: str, video_url: str, entries: list[dict]) -> str:
    import_id, now = str(uuid4()), utc_now()
    with connect() as db:
        db.execute("INSERT INTO clipwing_imports(id,project_id,video_url,analysis_text,status,stage,progress,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (import_id, project_id, video_url, analysis_text, "queued", "queued", 0, now, now))
        db.executemany("INSERT INTO clipwing_entries(id,import_id,ordinal,title,start_seconds,end_seconds,score,transcript,video_url,status,progress) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       [(str(uuid4()), import_id, item["ordinal"], item["title"], item["start_seconds"], item["end_seconds"], item["score"], item["transcript"], item["video_url"], "queued", 0) for item in entries])
    return import_id


def get_import(import_id: str):
    with connect() as db:
        job = db.execute("SELECT * FROM clipwing_imports WHERE id=?", (import_id,)).fetchone()
        if not job:
            return None
        result = dict(job)
        try:
            result["formats"] = json.loads(result.pop("formats_json", "[]"))
        except (TypeError, json.JSONDecodeError):
            result["formats"] = []
        result["entries"] = [dict(row) for row in db.execute("SELECT * FROM clipwing_entries WHERE import_id=? ORDER BY ordinal", (import_id,)).fetchall()]
    return result


def list_imports(project_id: str):
    with connect() as db:
        ids = [row[0] for row in db.execute("SELECT id FROM clipwing_imports WHERE project_id=? ORDER BY created_at DESC LIMIT 20", (project_id,)).fetchall()]
    return [get_import(import_id) for import_id in ids]


def set_job(import_id: str, *, status: str, stage: str, progress: float, error_message: str | None = None) -> None:
    with connect() as db:
        db.execute("UPDATE clipwing_imports SET status=?,stage=?,progress=?,error_message=?,updated_at=? WHERE id=?",
                   (status, stage[:80], max(0, min(1, progress)), error_message[:1000] if error_message else None, utc_now(), import_id))


def set_video_metadata(import_id: str, *, title: str, duration_seconds: float | None, formats: list[dict]) -> None:
    with connect() as db:
        db.execute("UPDATE clipwing_imports SET video_title=?,video_duration_seconds=?,formats_json=? WHERE id=?",
                   (title[:300], duration_seconds, json.dumps(formats, separators=(",", ":")), import_id))


def get_entry(entry_id: str):
    with connect() as db:
        row = db.execute("SELECT * FROM clipwing_entries WHERE id=?", (entry_id,)).fetchone()
    return dict(row) if row else None


def set_entry(entry_id: str, *, status: str, progress: float = 0, error_message: str | None = None, media_id: str | None = None, clip_id: str | None = None, caption_source: str | None = None, selected_format_id: str | None = None) -> None:
    with connect() as db:
        db.execute("UPDATE clipwing_entries SET status=?,progress=?,error_message=?,media_id=COALESCE(?,media_id),clip_id=COALESCE(?,clip_id),caption_source=COALESCE(?,caption_source),selected_format_id=COALESCE(?,selected_format_id) WHERE id=?",
                   (status, max(0, min(1, progress)), error_message[:1000] if error_message else None, media_id, clip_id, caption_source, selected_format_id, entry_id))


def register_cut(*, entry_id: str, project_id: str, media_id: str, clip_id: str, filename: str, relative_source_path: str, size_bytes: int, metadata) -> None:
    now = utc_now()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO media(id,project_id,original_filename,source_relative_path,size_bytes,duration_seconds,width,height,frame_rate,frame_rate_decimal,video_codec,audio_codec,has_audio,container_format,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (media_id, project_id, filename, relative_source_path, size_bytes, metadata.duration_seconds, metadata.width, metadata.height, metadata.frame_rate, metadata.frame_rate_decimal, metadata.video_codec, metadata.audio_codec, int(metadata.has_audio), metadata.container_format, now))
        entry = db.execute("SELECT title FROM clipwing_entries WHERE id=?", (entry_id,)).fetchone()
        db.execute("INSERT INTO clips(id,project_id,media_id,source_candidate_id,title,start_seconds,end_seconds,created_at,updated_at) VALUES(?,?,?,NULL,?,0,?,?,?)",
                   (clip_id, project_id, media_id, entry["title"], metadata.duration_seconds, now, now))
        db.execute("UPDATE clipwing_entries SET status='ready',progress=1,error_message=NULL,media_id=?,clip_id=? WHERE id=?",
                   (media_id, clip_id, entry_id))
        db.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))


def queued_import_ids() -> list[str]:
    with connect() as db:
        return [row[0] for row in db.execute("SELECT id FROM clipwing_imports WHERE status='queued' ORDER BY created_at").fetchall()]


def interrupt_active_imports() -> None:
    with connect() as db:
        now = utc_now()
        db.execute("UPDATE clipwing_entries SET status='interrupted',progress=0,error_message='Clip download was interrupted by application restart.' WHERE status='cutting' OR (status='queued' AND import_id IN (SELECT id FROM clipwing_imports WHERE status IN ('downloading','cutting')))")
        db.execute("UPDATE clipwing_imports SET status='interrupted',stage='interrupted',error_message='Video details lookup or clip download was interrupted by application restart.',updated_at=? WHERE status IN ('downloading','cutting')", (now,))
