# CLIPRA.AI

CLIPRA.AI is a local-first Windows application for organizing and editing authorized video. It supports local projects, imported media, FFprobe metadata, SQLite persistence, range-based playback, editable clips, captions, split-screen layouts, and versioned exports. Social packages can be reviewed and explicitly published as YouTube Shorts, Facebook Reels, and Instagram Reels. Instagram temporarily stages approved Reels in Cloudflare R2 for Meta to fetch; Facebook and YouTube use their existing upload paths. You can paste timestamped suggestions from an external video-analysis service such as Clipwing and import those segments as individual editable clips.

Clipwing suggestions remain user-provided input; each selected segment is downloaded as a separate managed MP4 and opened as an editable draft. Stage 4 adds optional, local faster-whisper transcription and editable caption tracks. Stage 5 renders each approved clip once as a versioned MP4.

## Requirements

- Windows 11 with PowerShell
- Node.js 24.x and npm 11.x
- Python 3.13 (the backend virtual environment is created with `py -3.13`)
- Git for Windows
- FFmpeg and FFprobe on `PATH` (or explicit executable paths in `backend/.env`)

The Stage 1 implementation was verified with Python `3.13.17`, Node `v24.21.0`, npm `11.19.0`, and FFmpeg/FFprobe `9.0.2` on Windows 11 Pro.

## First-time setup (PowerShell)

Run these commands from the repository root (`E:\Website\CLIPRA-AI`). The venv check preserves an existing `backend/.venv`; it only creates one if absent. The `.env` checks also preserve existing local configuration.

```powershell
py -3.13 --version
New-Item -ItemType Directory -Force projects, temp, logs, database | Out-Null
if (-not (Test-Path .\backend\.venv\Scripts\python.exe)) { py -3.13 -m venv backend/.venv }
& .\backend\.venv\Scripts\python.exe -m pip install --upgrade pip==26.3
& .\backend\.venv\Scripts\python.exe -m pip install -r .\backend\requirements-lock.txt
if (-not (Test-Path .\backend\.env)) { Copy-Item .\backend\.env.example .\backend\.env }
if (-not (Test-Path .\frontend\.env)) { Copy-Item .\frontend\.env.example .\frontend\.env }
Push-Location .\frontend
npm ci
Pop-Location
```

The Python lock includes pinned runtime and test dependencies. Direct runtime pins are in `backend/requirements.txt`; pinned test dependencies are in `backend/requirements-dev.txt`. Gemini remains optional for Smart Crop focal-point suggestions only. Clipwing import uses pinned `yt-dlp` and does not require Gemini.

## Configuration

Edit `backend/.env` to configure local storage, upload limits, or tool locations. The default workspace is the repository root; the default upload limit is 20 GiB per file.

```dotenv
CLIPRA_WORKSPACE_DIR=
YOUTUBE_CLIENT_SECRETS_FILE=
CLIPRA_MAX_UPLOAD_BYTES=21474836480
CLIPRA_MAX_FILES_PER_IMPORT=20
CLIPRA_MAX_LAYOUT_IMAGE_BYTES=26214400
CLIPRA_FFPROBE=
CLIPRA_FFMPEG=
CLIPRA_FFPROBE_TIMEOUT_SECONDS=45
CLIPRA_PREVIEW_TIMEOUT_SECONDS=3600
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_TIMEOUT_SECONDS=300
GEMINI_FILE_MAX_BYTES=2147483648
GEMINI_FILE_POLL_TIMEOUT_SECONDS=600
GEMINI_MAX_OUTPUT_TOKENS=8192
GEMINI_INTERACTION_TIMEOUT_SECONDS=1800
R2_ACCOUNT_ID=
R2_BUCKET=clipra-ai
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
CLIPRA_FRAMING_EXTRACT_TIMEOUT_SECONDS=60
CLIPRA_FRAMING_MAX_FRAME_BYTES=3145728
CLIPRA_TRANSCRIPTION_MAX_SECONDS=900
CLIPRA_TRANSCRIPTION_TIMEOUT_SECONDS=3600
CLIPRA_TRANSCRIPTION_MODEL=small.en
```

Leave `CLIPRA_WORKSPACE_DIR` empty to use the repository workspace, or set it to an absolute path such as `D:\CLIPRA-Workspace`. Leave the executable settings empty to use `PATH`. The upload limit is in bytes and applies independently to each file. The UI displays the limit returned by the backend health endpoint.

Gemini key and model settings are read only by backend code and are used for optional Smart Crop suggestions. Do not put secrets in frontend configuration. No video highlight-analysis feature uploads a video to Gemini.

Each Smart Crop request requires explicit confirmation and sends three selected still frames from the managed clip to Google. It may consume API quota or incur charges. Source videos remain unchanged.

Instagram publishing also requires Cloudflare R2 credentials in `backend/.env`. CLIPRA uploads the approved MP4 to the configured bucket under `ig-reels/`, creates a two-hour signed GET URL, and verifies that it returns the exact MP4 directly before giving it to Instagram. Configure a one-day R2 lifecycle deletion rule for the exact `ig-reels/` prefix. The signed URL is never logged or returned to the UI. Use the standalone connection check after adding the credentials:

```powershell
& .\backend\.venv\Scripts\python.exe .\backend\scripts\check_instagram_r2.py
```

The check uploads a tiny disposable object, prints the GET URL location with its signed query redacted, validates the same object through a separately signed HEAD URL (SigV4 signs the HTTP method), and deletes the object. It does not contact Instagram.

The backend-only diagnostic makes one minimal text-generation request to the configured model. It does not upload video or modify billing settings. Run it from the repository root only when you want to test the connection:

```powershell
& .\backend\.venv\Scripts\python.exe .\backend\scripts\check_gemini_connection.py
```

## Run the application

Open two PowerShell terminals in the repository root.

Terminal 1 starts the backend at `http://127.0.0.1:8000`:

```powershell
& .\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir .\backend --host 127.0.0.1 --port 8000 --reload
```

Terminal 2 starts the frontend at `http://127.0.0.1:5173`:

```powershell
Push-Location .\frontend
npm run dev
```

Open `http://127.0.0.1:5173`. Stop each server with `Ctrl+C`; then run `Pop-Location` in the frontend terminal to return to the repository root.

## Import videos and Clipwing suggestions

1. Select **New project**, enter a project name, and create it.
2. In the project, choose or drop one or more MP4, MOV, MKV, AVI, or WebM files.
3. Select **Import**. Each file uploads independently and is validated by FFprobe. A failed file does not prevent other files from importing.
4. Review real metadata in **Imported videos** and open the playback preview if desired.
5. In the project’s **Paste Clipwing analysis** section, paste results containing numbered titles, timestamp ranges, optional scores and transcript excerpts, and a YouTube link for the same video. Confirm that you have permission to download and edit that public video, then choose **Check video details**.
6. CLIPRA performs a metadata lookup once for the shared video and displays its title, duration, and available format/resolution choices beside each suggestion. It does not download the video during this step. Choose the quality for each clip and click that row’s **Download clip** button to begin only that range. Each row shows its own progress.
7. The selected range is downloaded and recompressed into a managed MP4 with H.264 video and AAC audio. This takes processing time, but CLIPRA does not download the complete source video. A source that is private, unavailable, region-restricted, or otherwise inaccessible without an account cannot be imported. This does not bypass access controls or platform restrictions.
8. Each completed clip appears in the project library and can be opened independently in the editor. YouTube subtitles are not fetched. To create captions, explicitly download a faster-whisper model, then choose **Transcribe clip locally** in that clip’s editor. Whisper processes the clip locally.
9. Use **New clip** on an imported video for a manual draft. In the editor, set exact in/out times, choose a framing/layout, and save. Choose **Split-Screen Streamer + Gameplay** for separate top/bottom framing, crop, zoom and position settings; the top can use the same video, a managed custom image, or a solid color.
10. Edit captions and styling in the editor, then click **Export** to approve and render one version. Exports are kept independently; editing and exporting again creates the next version.

Smart Crop recommendations are optional. Before each request, the user must check an explicit consent box. CLIPRA extracts three small still frames from the selected clip locally and sends those images—not necessarily the full video—to Google through the official GenAI SDK. The request may use API quota or incur charges depending on the Google AI Studio project and current terms. No request is made if consent is declined. Request status and results are stored locally; duplicate active/completed requests are not repeated unless explicitly retried after a failure. Temporary local frame files are removed after processing. Original source files remain unchanged.

The browser uploads a copy into the CLIPRA workspace. It never sends a source path for the app to modify, move, or overwrite. The original file remains where the user selected it. Managed copies use generated filenames under `projects/<project-id>/sources/`.

Playback streams support HTTP byte ranges, so the video element can seek without loading the whole file into memory. If the browser cannot play a source format or codec, CLIPRA creates a separate H.264/AAC MP4 playback copy under `projects/<project-id>/previews/`. The player displays the preparation status and keeps the source separate. Preview generation can take time and consumes additional disk space; if FFmpeg fails, the player shows the error and offers a retry.

FFprobe/FFmpeg support depends on the installed build and the media's codecs. A file can be importable even if the browser cannot play its source directly; the playback proxy is used for that case.

YouTube source downloads depend on the video being publicly accessible to the downloader and on YouTube’s current delivery behavior. Some videos may fail to download. CLIPRA does not support sign-in cookies, private videos, access-control bypass, or automatic publishing. The chosen MP4 cut is re-encoded at CRF 18 to make the exact requested timestamps and ensure H.264/AAC compatibility; this can take longer and is not a stream copy.

## Local storage and database

The workspace paths are created as needed:

```text
database/clipra.sqlite3
projects/<project-id>/sources/<media-id>.<original-extension>
projects/<project-id>/previews/<media-id>.mp4
temp/uploads/                     # transient upload staging
temp/framing/                     # transient, consented still-frame extraction
temp/transcription/               # transient, local clip-audio extraction
models/faster-whisper/            # explicitly downloaded local model snapshots

projects/<project-id>/exports/<clip-id>/         # independent V1, V2, ... MP4 outputs
projects/<project-id>/layout-images/             # validated split-layout still images
temp/rendering/                    # transient Chromium caption frames and partial MP4 files
```

SQLite schema version 18 contains:

- `projects`: ID, name, creation timestamp, and last-updated timestamp.
- `media`: project relationship, original filename, managed relative source path, actual byte size, duration, width, height, rational and decimal frame rate, video codec, audio codec and availability, FFprobe container format, preview status/path/error, and import timestamp.
- `clipwing_imports` and `clipwing_entries`: project-level pasted analysis, normalized single-video URL, safe format/resolution metadata (no signed media URLs), per-entry timestamps/score/transcript/format selection, persistent per-clip download progress and status, and links to resulting media and editable clips.
- Legacy `analysis_runs` and `analysis_candidates` tables remain for database compatibility; the Gemini highlight-analysis API and UI are removed. Startup marks any old active Gemini analysis rows interrupted.
- `clips`: editable source time boundaries, title, project/media relationship, optional originating suggestion, framing mode and local manual focus/zoom/blur settings, persisted manual focal-point override, and Smart Crop request state.
- `clip_focal_points`: ordered timestamped normalized focal points, optional confidence, and cascading clip relationship. Recommendation status, model, timestamps and sanitized failure details are stored on the clip. Pending requests are marked failed on restart instead of being repeated automatically.
- `transcription_runs`: one local transcription attempt for a clip, including explicit model ID, language, device profile, source-boundary snapshot, status, and sanitized failure data. Runs interrupted while in external/local worker activity are not automatically replayed.
- `caption_tracks`: editable caption draft metadata, canonical future ASS/FFmpeg-compatible style settings, grouping rules, normalized preview position, safe-zone profile, source-boundary snapshot, and stale indicator.
- `caption_segments` and `caption_words`: grouped phrases plus word-level times, confidence, original text, and user-edited text.
- `render_jobs`: immutable JSON configuration snapshots and hashes, per-clip export status and progress, selected output profile, explicit approval timestamps, unique output paths, and monotonically increasing export version numbers. Render history is retained independently of editable clip rows.
- `clips.layout_type` and `clips.split_layout_json`: Original Layout default and isolated split-screen settings for both sections, including top source/image/color, framing, zoom, position, and divider ratio.
- `clip_layout_assets`: validated PNG/JPG/WebP metadata and managed paths for uploaded top-section images. Image files are not automatically deleted when a layout changes or a render snapshot references them.
- `social_content_generations`: generation attempts associated with one immutable export version, per-run consent, model and prompt versions, progress/recovery state, validated generated packages, separate editable package values, and pending Google cleanup references. This data remains local in SQLite; no post is published.
- `instagram_uploads`: explicitly approved Instagram Reels publications, the selected Page and linked Instagram account, per-export progress, final media ID/permalink, Meta container ID, temporary R2 object key, and interruption state. Credentials remain encrypted separately in the local Windows user workspace.

The database uses foreign-key checks and write-ahead logging. Media paths stored in SQLite are relative and are resolved and checked against the configured workspace before access. Databases, projects, uploaded media, previews, temporary files, exports, and logs are excluded from Git.

## Backend API

Interactive OpenAPI documentation is available at `http://127.0.0.1:8000/docs` while the backend is running.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Backend status and effective per-file upload/file-count limits. |
| POST | `/api/projects` | Create a project using `{ "name": "..." }`. |
| GET | `/api/projects` | List projects and imported media counts. |
| GET | `/api/projects/{project_id}` | Get a project and its real media metadata. |
| POST | `/api/projects/{project_id}/media` | Multipart upload; repeat the `files` field for multiple files. Returns independent imported/failed results. |
| POST | `/api/projects/{project_id}/clipwing-imports` | Start an authorized Clipwing text import after `{ "confirm_rights": true }`. |
| GET | `/api/projects/{project_id}/clipwing-imports` | List recent Clipwing imports and entries. |
| GET | `/api/projects/{project_id}/clipwing-imports/{import_id}` | Read download/cut progress and generated clip links. |
| POST | `/api/projects/{project_id}/clipwing-imports/{import_id}/entries/{entry_id}/download` | Download one suggested time range in its selected source format/resolution, then create an H.264/AAC MP4. |
| GET, HEAD | `/api/media/{media_id}/stream` | Stream the imported source; supports single HTTP byte ranges and seeking. |
| POST | `/api/media/{media_id}/preview` | Generate or reuse a separate H.264/AAC preview copy. |
| GET, HEAD | `/api/media/{media_id}/preview/stream` | Stream the generated preview with byte-range support. |
| GET | `/api/media/{media_id}/clips` | List draft clips for a source video. |
| POST | `/api/media/{media_id}/clips` | Create a manual draft with `title`, `start_seconds`, and `end_seconds`. |
| GET | `/api/clips/{clip_id}` | Inspect a draft and its framing request state/focal points. |
| PATCH | `/api/clips/{clip_id}` | Update title, source boundaries, framing mode, manual focus, zoom, or blur settings. |
| GET | `/api/clips/{clip_id}/layout-images` | List the clip’s managed custom split-layout images. |
| POST | `/api/clips/{clip_id}/layout-images` | Validate and store a PNG/JPG/WebP image for the split-layout top section. |
| GET | `/api/layout-images/{asset_id}` | Stream a validated managed layout image. |
| POST | `/api/clips/{clip_id}/framing-suggestion` | Request an optional Smart Crop recommendation after explicit `{ "consent_to_send_frames": true }`; set `retry: true` only to explicitly repeat a failed request. |
| GET | `/api/transcription/hardware-profile` | Local CPU, memory/disk profile and model recommendation. Transcription runs on CPU INT8. |
| GET | `/api/transcription/models` | Supported local faster-whisper models and installed state. |
| POST | `/api/transcription/models/{model_id}/download` | Explicitly start a local model download; no model downloads automatically. |
| POST | `/api/clips/{clip_id}/transcriptions` | Queue local transcription for an installed model. |
| GET | `/api/clips/{clip_id}/transcriptions` | Retrieve local transcription history. |
| GET, POST | `/api/clips/{clip_id}/caption-tracks` | List or create editable caption drafts. |
| GET, PATCH | `/api/caption-tracks/{track_id}` | Retrieve/update preset, render-compatible style, position, safe zone, and grouping. |
| POST | `/api/caption-tracks/{track_id}/reflow` | Re-group persisted word timings into readable phrases. |
| PATCH | `/api/caption-segments/{segment_id}`, `/api/caption-words/{word_id}` | Edit persisted phrase or word content/timing. |
| GET | `/api/clips/{clip_id}/render-jobs` | Read immutable export version history. |
| GET | `/api/render-jobs/{job_id}` | Inspect render state and progress. |
| GET, HEAD | `/api/render-jobs/{job_id}/stream` | Play completed exports with HTTP byte-range seeking. |
| GET | `/api/render-jobs/{job_id}/download` | Download a completed export MP4. |
| POST | `/api/render-jobs/{render_job_id}/social-content-generations` | Start Stage 6 after explicit per-run consent to upload that completed export and context to Google Gemini. |
| GET | `/api/render-jobs/{render_job_id}/social-content-generations` | Read generation attempts and packages for an exact export version. |
| GET | `/api/social-content-generations/{generation_id}` | Inspect social generation progress and saved package state. |
| GET | `/api/social-content-generations/{generation_id}/manual-prompt` | Copy the exact export-specific social prompt after a Gemini failure. |
| POST | `/api/social-content-generations/{generation_id}/manual-import` | Validate pasted AI JSON and populate all four social packages after a Gemini failure. |
| PATCH | `/api/social-content-generations/{generation_id}/platforms/{platform}` | Save user edits to one platform package. |
| GET | `/api/social/youtube/status` | Check whether a local Desktop OAuth client is configured and YouTube is connected. |
| POST | `/api/social/youtube/connect` | Open Google's Desktop OAuth consent in the system browser using PKCE and a random loopback port. |
| DELETE | `/api/social/youtube/connection` | Revoke and remove the locally stored YouTube authorization. |
| POST | `/api/social/youtube/exports/{render_job_id}/uploads` | Explicitly upload the selected completed export using its saved YouTube Shorts package and chosen privacy. |
| GET | `/api/social/youtube/exports/{render_job_id}/uploads` | List uploads and progress for the exact export version. |
| GET | `/api/social/youtube/uploads/{upload_id}` | Inspect one upload's state and final YouTube URL. |
| GET | `/api/social/facebook/status` | Check local Facebook app configuration, connection state, and Pages returned by Meta. |
| POST | `/api/social/facebook/connect` | Open Facebook OAuth in the browser and retrieve managed Pages after consent. |
| DELETE | `/api/social/facebook/connection` | Clear Facebook Page tokens encrypted for the current Windows user. |
| POST | `/api/social/facebook/exports/{render_job_id}/uploads` | Explicitly publish the selected completed export as a Facebook Reel with its saved package to a chosen Page. |
| GET | `/api/social/facebook/exports/{render_job_id}/uploads` | List Facebook upload states and progress for the exact export version. |
| GET | `/api/social/facebook/uploads/{upload_id}` | Inspect one Facebook upload and its resulting Reel URL. |
| GET | `/api/social/instagram/status` | Check Meta configuration and professional Instagram accounts linked to authorized Pages. |
| POST | `/api/social/instagram/connect` | Reopen the shared Meta OAuth flow to grant Instagram permissions and discover linked Instagram accounts. |
| POST | `/api/social/instagram/exports/{render_job_id}/uploads` | Publish a completed export as an Instagram Reel with its saved package after explicit `{ "approved": true }` approval, using Instagram Graph API v25.0 `video_url` and temporary Cloudflare R2 storage. |
| GET | `/api/social/instagram/exports/{render_job_id}/uploads` | List Instagram Reel publication states and progress for the exact export. |
| GET | `/api/social/instagram/uploads/{upload_id}` | Inspect one Instagram publication and its resulting permalink. |

Stage 5 exports one clip at a time at 9:16. The Export page always offers 1080 x 1920 and offers 1440 x 2560 only when FFprobe reports the original upload is at least 1440p (both source dimensions are at least 1440 pixels). Lower-resolution uploads are limited to 1080p. A 1440p landscape source can still be upscaled after a vertical crop, so larger output dimensions do not restore cropped detail. Clicking **Export** is the explicit approval and starts the only render pass. The renderer uses the current saved framing and caption settings, including Chromium-rendered caption frames from the editor's `CaptionOverlay` CSS, with FFmpeg for video composition. Final exports use H.264 CRF 18 with the medium preset and AAC at 160 kb/s. The chosen output profile is stored in each immutable render snapshot, so versions can use different resolutions without changing the editable draft or prior exports. Each export is an immutable V1, V2, and later version; editing resumes on the same draft and never overwrites an earlier output. Source media and completed exports are not automatically deleted. Existing Stage 5 preview files are retained locally but are not generated or shown by the current workflow. Imported-media playback compatibility previews remain separate.

The split-screen add-on keeps the same output profile and Stage 5 approval/version behavior. A single source video branches into synchronized top and bottom filters; only its original audio stream is mapped. A custom image is looped for the top, or a solid color can fill it, while the source clip supplies the bottom and audio. Captions use the editor's Chromium component and are composited after the sections are stacked; preset colors, shadows, text sizing, word highlighting, and animations use the same CSS as the editor. Each section's framing, zoom, and position settings are independent. Images are limited by `CLIPRA_MAX_LAYOUT_IMAGE_BYTES` (25 MiB by default), an 8192-pixel maximum side, and a 40-megapixel maximum. Replacing an image reference does not delete its managed file.

`GET /api/health` reports whether Gemini is configured for optional Smart Crop suggestions and Stage 6 social copy. It never returns the key.

Unsatisfiable or unsupported ranges receive HTTP `416`; successful partial playback requests receive `206 Partial Content`. Missing managed sources return `410 Gone`; unknown projects/media return `404`.

## Tests and build

From the repository root:

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest .\backend\tests -q
Push-Location .\frontend
npm test
npm run build
Pop-Location
```

Backend tests generate short synthetic videos and images with FFmpeg locally. They cover Stages 1–5 plus split-layout migration, independent settings, image validation/storage, synchronized composition, single audio mapping, 9:16 output, and image retention. Frontend tests cover clip ranges, caption behavior, split positioning, and divider bounds. Transcription-model inference is mocked in automated tests; a real faster-whisper semantic transcription is intentionally not performed unless a user explicitly downloads a model. The suite does not upload real videos or frames to Google. No copyrighted fixture videos are used.

## Troubleshooting

- **API offline in the UI:** start the backend terminal and check `Invoke-RestMethod http://127.0.0.1:8000/api/health`.
- **FFprobe or FFmpeg not found:** verify `ffprobe -version` and `ffmpeg -version`. Add the FFmpeg `bin` folder to `PATH` or set `CLIPRA_FFPROBE`/`CLIPRA_FFMPEG` to the executable paths in `backend/.env`.
- **Upload exceeds limit:** increase `CLIPRA_MAX_UPLOAD_BYTES` in `backend/.env` and restart the backend. Ensure the managed workspace drive has enough space for the uploaded source copy and any generated preview.
- **Unsupported or corrupt video:** confirm FFprobe supports the container and codecs. The original selected file remains unchanged if import fails.
- **Preview failed:** read the displayed FFmpeg error, verify FFmpeg can encode H.264 (`ffmpeg -hide_banner -encoders`), and retry. The original source file is still stored separately.
- **Port already in use:** stop the other process using port 8000 or 5173 before starting CLIPRA.AI.

## Development stages

- Stage 0: environment, project foundation, and live health check.
- Stage 1: local projects, multi-file import, FFprobe metadata, SQLite persistence, playback, and compatible preview copies.
- Stage 2: paste external timestamped suggestions, download authorized public source video, and create independent editable clips (implemented; an actual YouTube download was not used for verification).
- Stage 3: draft clip editing and optional focal-point framing recommendations (implemented; approval and export are not included).
- Stage 4: local faster-whisper transcription and editable caption drafts (implemented; Stage 5 exports captions with the editor's Chromium component).
- Stage 5: direct approved export, immutable versioned MP4s, playback/download, and editing after export (implemented; export uses H.264 CRF 18).
- Stage 6: consented per-export Gemini social copy for Instagram Reels, YouTube Shorts, and Facebook Reels, with persistent progress, editable packages, and explicit regeneration (implemented; automated tests mock Google and do not make billable requests).
- Stage 7: user-connected YouTube account, reviewed YouTube Shorts package, explicit per-upload approval, privacy selection, resumable transfer, and per-export upload history (implemented; live Google authorization/upload requires your own credentials and has not been run here).
- Stage 8: user-connected Facebook Pages, reviewed Facebook Reels package, explicit per-upload approval, managed Page selection, resumable local transfer progress, and per-export upload history (implemented; live Meta authorization/upload requires your own app and Page and has not been run here).
- Stage 9: user-connected Instagram Business/Creator account linked to a Facebook Page, reviewed Instagram Reels package, explicit per-upload approval, temporary Cloudflare R2 hosting with Graph API `video_url`, Meta processing checks, and per-export upload history (implemented; automated checks mock Meta and R2; live authorization/upload has not been run here).
- Split-Screen Streamer + Gameplay add-on after Stage 5: optional vertical same-video or custom-image composition integrated with direct Stage 5 exports (implemented; no face detection or batch workflow).

See [Clipwing import details](docs/clipwing-import.md) for accepted input format, format selection, per-clip progress, storage behavior, and restart handling.
See [Custom Text and Original Layout crop](docs/custom-text-and-original-crop.md) for the editor's independent text overlay and top/bottom crop controls.
Split-screen top and bottom sections also have separate vertical trim controls; see [split-screen layout details](docs/split-screen-layout.md).
See [Stage 6 social content](docs/stage6-social-content.md) for the per-export consent, upload, package editing, quota, and recovery behavior.
See [YouTube publishing](docs/stage7-youtube-publishing.md) for credential placement, local token protection, upload behavior, Google Cloud test-mode limits, and API routes.
See [Facebook Page publishing](docs/stage8-facebook-publishing.md) for Meta app setup, the OAuth callback URL, local credentials, Page permissions, and upload behavior.
See [Instagram Reels publishing](docs/stage9-instagram-publishing.md) for linked-account requirements, permissions, per-export approval, upload behavior, and Meta's media constraints.

