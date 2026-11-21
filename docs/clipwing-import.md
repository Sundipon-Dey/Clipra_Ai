# Clipwing analysis import

CLIPRA accepts pasted, numbered suggestions from Clipwing or another analysis service. Example:

```text
1. Highlight title (0:53-2:06, score 95)
"Transcript excerpt"
https://youtu.be/VIDEO_ID?t=53
```

All entries in one import must reference the same YouTube video. CLIPRA supports up to 40 entries per import, requires positive ranges no longer than 30 minutes, and retains the quoted excerpt as descriptive suggestion text. The excerpt is not used as timed captions.

## Metadata, formats, and downloads

After the user confirms permission, CLIPRA performs one metadata lookup for the shared video. It stores the title, duration, and sanitized format metadata (format ID, resolution, container, codecs, frame rate, and estimated size). Signed media URLs are held in process memory only and are never included in API responses or saved in SQLite. The initial lookup does not download the video.

The UI lists each available video format/resolution on every suggestion. The user chooses a format per clip and must click that clip's Download button. CLIPRA uses yt-dlp section downloads and FFmpeg to fetch and recompress only the requested range, with keyframes forced at the cut boundaries, into an H.264/AAC MP4. Output uses CRF 18 and medium preset. This processing takes time proportional to the selected clips; it does not download the complete source video. For formats that need conversion to MP4, FFmpeg may perform an additional conversion pass.

Each entry has its own status and progress value in SQLite; the web UI shows a separate progress bar for every clip. Completed clips are stored at:

```text
projects/<project-id>/sources/<media-id>.mp4
```

Queued metadata lookups resume after restart. Lookups already in progress and clip downloads already underway are marked interrupted and are not automatically repeated. A future download after restart may need to refresh the metadata because signed format URLs intentionally are not persisted. Unavailable or expired formats can fail; retry after refreshing the lookup by pasting the analysis again.

The user must confirm they have permission to download and edit the public video. CLIPRA does not use account cookies, sign in, bypass access controls, or publish content. Private, unavailable, age/account-gated, region-restricted, or otherwise inaccessible videos may fail.

## Captions

YouTube subtitle files are not fetched or imported. Users can create captions with local faster-whisper from each clip's editor. No transcription model is downloaded automatically.

## Database and API

Schema version 10 adds sanitized metadata and per-entry format selection to `clipwing_imports` and `clipwing_entries`. The API is project-scoped:

- `POST /api/projects/{project_id}/clipwing-imports` starts the metadata lookup after `confirm_rights: true`.
- `GET /api/projects/{project_id}/clipwing-imports` lists recent import records.
- `GET /api/projects/{project_id}/clipwing-imports/{import_id}` reads metadata and per-clip progress.
- `POST /api/projects/{project_id}/clipwing-imports/{import_id}/entries/{entry_id}/download` starts one clip download with the chosen `format_id`.

See the local OpenAPI page at `/docs` for request and response fields.
