"""Single-range byte streaming for browser video playback and seeking."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import StreamingResponse


RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")
STREAM_CHUNK_BYTES = 256 * 1024


def byte_range(range_header: str | None, size: int) -> tuple[int, int, bool]:
    if size <= 0:
        raise HTTPException(status_code=416, detail="This video file is empty.")
    if not range_header:
        return 0, size - 1, False
    match = RANGE_PATTERN.fullmatch(range_header.strip())
    if match is None:
        raise HTTPException(status_code=416, detail="Only one valid byte range is supported.", headers={"Content-Range": f"bytes */{size}"})
    start_text, end_text = match.groups()
    if len(start_text) > 20 or len(end_text) > 20:
        raise HTTPException(status_code=416, detail="The requested byte range is invalid.", headers={"Content-Range": f"bytes */{size}"})
    if not start_text and not end_text:
        raise HTTPException(status_code=416, detail="The requested byte range is invalid.", headers={"Content-Range": f"bytes */{size}"})
    if not start_text:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise HTTPException(status_code=416, detail="The requested byte range is invalid.", headers={"Content-Range": f"bytes */{size}"})
        start = max(0, size - suffix_length)
        end = size - 1
    else:
        start = int(start_text)
        end = min(int(end_text), size - 1) if end_text else size - 1
    if start >= size or end < start:
        raise HTTPException(status_code=416, detail="The requested byte range is not satisfiable.", headers={"Content-Range": f"bytes */{size}"})
    return start, end, True


def _read_range(path: Path, start: int, length: int) -> Iterator[bytes]:
    with path.open("rb") as source:
        source.seek(start)
        remaining = length
        while remaining:
            chunk = source.read(min(STREAM_CHUNK_BYTES, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def stream_file(path: Path, *, media_type: str, range_header: str | None) -> StreamingResponse:
    size = path.stat().st_size
    start, end, partial = byte_range(range_header, size)
    length = end - start + 1
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Cache-Control": "no-store",
        "Content-Disposition": "inline",
    }
    status_code = 206 if partial else 200
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        _read_range(path, start, length),
        status_code=status_code,
        media_type=media_type,
        headers=headers,
    )
