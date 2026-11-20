# CLIPRA.AI

CLIPRA.AI is a local-first Windows application for organizing, previewing, and finding highlight moments in authorized video footage. It supports local projects, multiple video imports, real FFprobe metadata, SQLite persistence, range-based playback, separate preview copies, explicit Gemini video analysis, and editable draft clips with vertical framing.

Stage 2 suggestions remain recommendations until a user turns one into an editable draft clip. Stage 4 adds optional, local faster-whisper transcription and editable caption tracks. Stage 5 adds an explicit rendered preview, separate approval, and immutable versioned MP4 exports.

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

The Python lock includes pinned runtime and test dependencies. Direct runtime pins are in `backend/requirements.txt`; pinned test dependencies are in `backend/requirements-dev.txt`. Stage 2 uses the official Google `google-genai` Python SDK; it does not download AI models.

## Configuration

Edit `backend/.env` to configure local storage, upload limits, or tool locations. The default workspace is the repository root; the default upload limit is 20 GiB per file.

```dotenv
CLIPRA_WORKSPACE_DIR=
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
CLIPRA_FRAMING_EXTRACT_TIMEOUT_SECONDS=60
CLIPRA_FRAMING_MAX_FRAME_BYTES=3145728
CLIPRA_TRANSCRIPTION_MAX_SECONDS=900
CLIPRA_TRANSCRIPTION_TIMEOUT_SECONDS=3600
CLIPRA_TRANSCRIPTION_MODEL=small.en
```

Leave `CLIPRA_WORKSPACE_DIR` empty to use the repository workspace, or set it to an absolute path such as `D:\CLIPRA-Workspace`. Leave the executable settings empty to use `PATH`. The upload limit is in bytes and applies independently to each file. The UI displays the limit returned by the backend health endpoint.

The Gemini key and model settings are read only by backend code. Do not put secrets in frontend configuration. The default model is `gemini-3.5-flash-lite`; `GEMINI_MODEL` remains configurable. The configured model and key are used by backend code only. `GEMINI_TIMEOUT_SECONDS` applies to each SDK HTTP request; `GEMINI_INTERACTION_TIMEOUT_SECONDS` limits the server-side analysis duration. Automatic SDK retries are disabled (`attempts=1`). The maximum individual upload defaults to 2 GiB, the documented Files API per-file limit. The Files API project storage limit is 20 GB and uploaded files expire after 48 hours; CLIPRA also attempts immediate deletion after analysis.

The Gemini API can consume free-tier quota and may be billable depending on the AI Studio project. Free-tier access, quota, model availability, and pricing can change. CLIPRA does not enable billing or guarantee free usage. Before every analysis, the UI identifies the video that will be uploaded and asks for confirmation. Only the managed copy is sent; the original file remains unchanged. No video is uploaded until the user explicitly starts analysis. Gemini background interactions are stored server-side by Google while active; CLIPRA deletes the interaction record and file after receiving and saving the result. Cleanup failure is shown and retried at restart where possible.

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

## Import, preview, and analyze videos

1. Select **New project**, enter a project name, and create it.
2. In the project, choose or drop one or more MP4, MOV, MKV, AVI, or WebM files.
3. Select **Import**. Each file uploads independently and is validated by FFprobe. A failed file does not prevent other files from importing.
4. Review real metadata in **Imported videos** and select **Open preview**.
5. To request highlight suggestions, choose **Analyze with Gemini**, review the external upload and quota notice, then confirm. CLIPRA uploads the managed source copy using the official Files API. Gemini's agentic video processing scans the timeline and examines promising sections. Long analysis runs use Gemini's server-side background interaction and are polled by the local job worker. This uses one model-analysis request; upload, interaction status polling, and cleanup are separate API operations.
6. Review the persisted timestamped suggestions. Select **Preview moment** to seek and play that interval in the existing player. Analysis can be run again explicitly; previous run history and candidates remain available.
7. Choose **Edit as clip** on a suggestion, or **New clip** on a video to create a manual draft. In the editor, set exact in/out times, seek the source, compare a responsive 9:16 preview, choose Smart Crop, Fit / Original, Blurred Background, or Manual Crop, then save. The editor and all manual controls work without Gemini.
8. Open **Captions & subtitles** in the clip editor. The hardware card recommends a local faster-whisper model. No transcription model is downloaded automatically: choose **Download model** explicitly, then choose **Transcribe clip locally**. The audio is extracted only to managed temporary storage and deleted after the local transcription completes or fails.
9. Choose one of seven render-compatible presets, select Phrase or One word text display, review phrase grouping and word timing, edit words, drag the caption inside the 9:16 preview, and use the safe-zone guides. One word mode shows only the word at its saved timing. Caption styling and display mode are persisted as draft data only; no final video is rendered in Stage 4.
10. In the clip editor, choose **Split-Screen Streamer + Gameplay** to stack a streamer section above gameplay. Choose Same Video, a PNG/JPG/WebP custom image, or a solid color for the top section. Select Top or Bottom controls to change each section’s fit/crop, zoom, and position independently. Drag content inside a pane to reposition it, or drag the divider to resize the sections. Save the draft, render a Stage 5 preview, review it, and explicitly approve the export.

Smart Crop recommendations are optional. Before each request, the user must check an explicit consent box. CLIPRA extracts three small still frames from the selected clip locally and sends those images—not necessarily the full video—to Google through the official GenAI SDK. The request may use API quota or incur charges depending on the Google AI Studio project and current terms. No request is made if consent is declined. Request status and results are stored locally; duplicate active/completed requests are not repeated unless explicitly retried after a failure. Temporary local frame files are removed after processing. Original source files remain unchanged.

The browser uploads a copy into the CLIPRA workspace. It never sends a source path for the app to modify, move, or overwrite. The original file remains where the user selected it. Managed copies use generated filenames under `projects/<project-id>/sources/`.

Playback streams support HTTP byte ranges, so the video element can seek without loading the whole file into memory. If the browser cannot play a source format or codec, CLIPRA creates a separate H.264/AAC MP4 playback copy under `projects/<project-id>/previews/`. The player displays the preparation status and keeps the source separate. Preview generation can take time and consumes additional disk space; if FFmpeg fails, the player shows the error and offers a retry.

FFprobe/FFmpeg support depends on the installed build and the media's codecs. A file can be importable even if the browser cannot play its source directly; the playback proxy is used for that case.

Gemini Files API currently documents a 2 GB per-file maximum and 20 GB total file storage per project. Agentic processing is documented for `gemini-3.5-flash-lite`; Gemini documents low-resolution videos up to 3 hours for models with a 1M-token context window. A video must also be in a Gemini-supported format and within the selected model's limits. Upload, processing, quota, timeout, and analysis failures are retained as run statuses with safe messages; paid generation requests are not automatically retried. Temporary uploaded files are deleted after a run where possible. If deletion fails or the app exits while a remote interaction is active, the UI marks cleanup as pending; the next startup attempts to cancel stale interactions and delete remote files. Google automatically expires Files API uploads after 48 hours.

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
projects/<project-id>/previews/clips/<clip-id>/ # rendered Stage 5 review previews
projects/<project-id>/exports/<clip-id>/         # independent V1, V2, ... MP4 outputs
projects/<project-id>/layout-images/             # validated split-layout still images
temp/rendering/                    # transient ASS caption scripts and partial MP4 files
```

SQLite schema version 8 contains:

- `projects`: ID, name, creation timestamp, and last-updated timestamp.
- `media`: project relationship, original filename, managed relative source path, actual byte size, duration, width, height, rational and decimal frame rate, video codec, audio codec and availability, FFprobe container format, preview status/path/error, and import timestamp.
- `analysis_runs`: project/media relationship, queued/uploading/processing/analyzing/completed/failed/interrupted status, model/prompt versions, source size, timestamps, safe error code/message, Gemini interaction/file references, and cleanup state. Only one active analysis per video is allowed. Queued work resumes on startup; in-flight external calls become `interrupted`, stale Gemini work is cancelled where possible, and generation is not automatically repeated.
- `analysis_candidates`: validated start/end seconds, title, description, category, reasoning, optional subjective confidence, and ordering linked to the run.
- `clips`: editable source time boundaries, title, project/media relationship, optional originating suggestion, framing mode and local manual focus/zoom/blur settings, persisted manual focal-point override, and Smart Crop request state.
- `clip_focal_points`: ordered timestamped normalized focal points, optional confidence, and cascading clip relationship. Recommendation status, model, timestamps and sanitized failure details are stored on the clip. Pending requests are marked failed on restart instead of being repeated automatically.
- `transcription_runs`: one local transcription attempt for a clip, including explicit model ID, language, device profile, source-boundary snapshot, status, and sanitized failure data. Runs interrupted while in external/local worker activity are not automatically replayed.
- `caption_tracks`: editable caption draft metadata, canonical future ASS/FFmpeg-compatible style settings, grouping rules, normalized preview position, safe-zone profile, source-boundary snapshot, and stale indicator.
- `caption_segments` and `caption_words`: grouped phrases plus word-level times, confidence, original text, and user-edited text.
- `render_jobs`: immutable JSON configuration snapshots and hashes, per-clip preview/export status and progress, explicit approval timestamps, unique output paths, and monotonically increasing export version numbers. Render history is retained independently of editable clip rows.
- `clips.layout_type` and `clips.split_layout_json`: Original Layout default and isolated split-screen settings for both sections, including top source/image/color, framing, zoom, position, and divider ratio.
- `clip_layout_assets`: validated PNG/JPG/WebP metadata and managed paths for uploaded top-section images. Image files are not automatically deleted when a layout changes or a render snapshot references them.

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
| GET, HEAD | `/api/media/{media_id}/stream` | Stream the imported source; supports single HTTP byte ranges and seeking. |
| POST | `/api/media/{media_id}/preview` | Generate or reuse a separate H.264/AAC preview copy. |
| GET, HEAD | `/api/media/{media_id}/preview/stream` | Stream the generated preview with byte-range support. |
| POST | `/api/media/{media_id}/analyses` | Start or reuse a run. Body `{ "force": true }` explicitly creates a new run after a prior terminal result. Repeated active requests reuse the current run. |
| GET | `/api/media/{media_id}/analyses` | Retrieve analysis history and candidates for each run. |
| GET | `/api/analyses/{analysis_id}` | Inspect one run and its current status/results. |
| GET | `/api/media/{media_id}/clips` | List draft clips for a source video. |
| POST | `/api/media/{media_id}/clips` | Create a manual draft with `title`, `start_seconds`, and `end_seconds`. |
| POST | `/api/analysis-candidates/{candidate_id}/clips` | Convert a Gemini suggestion into an independent editable draft. |
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
| POST | `/api/clips/{clip_id}/previews` | Render a 9:16 review file from the saved clip and current captions; optionally pass `{ "caption_track_id": "..." }` for a specific selected track. |
| GET | `/api/clips/{clip_id}/render-jobs` | Read preview and export history; indicates whether a completed preview still matches current edits. |
| GET | `/api/render-jobs/{job_id}` | Inspect render state and progress. |
| POST | `/api/render-jobs/{preview_id}/approve-export` | Explicitly approve a current, completed preview and queue an independent versioned MP4 export. |
| GET, HEAD | `/api/render-jobs/{job_id}/stream` | Play completed preview or export with HTTP byte-range seeking. |
| GET | `/api/render-jobs/{job_id}/download` | Download a completed export MP4. |

Stage 5 keeps the output profile fixed at 9:16 (1080 × 1920). Preview and export use the same framing, crop, blur, caption timing/position/style, and FFmpeg filter pipeline. Preview encoding uses a faster preset and lower quality. Approval is rejected if the saved clip or caption configuration changed after the preview. Export approval creates immutable V1, V2, and later versions; editing resumes on the same draft and never overwrites an earlier output. Source media and completed exports are not automatically deleted during normal editing or rendering. This workflow handles one clip at a time.

The split-screen add-on keeps the same output profile and Stage 5 approval/version behavior. A single source video branches into synchronized top and bottom filters; only its original audio stream is mapped. A custom image is looped for the top, or a solid color can fill it, while the source clip supplies the bottom and audio. Captions are composited after the sections are stacked, with preset colors, shadows, and timed word highlighting matching the editor; legacy outline widths do not draw text strokes. Every preset pops each active spoken word in both the editor and rendered output, while each preset’s own cue-entry animation remains applied. Each section’s framing, zoom, and position settings are independent. Images are limited by `CLIPRA_MAX_LAYOUT_IMAGE_BYTES` (25 MiB by default), an 8192-pixel maximum side, and a 40-megapixel maximum. Replacing an image reference does not delete its managed file.

`GET /api/health` also returns whether a Gemini key is configured, the model name, and the per-file Gemini limit. It never returns the key.

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
- Stage 2: Gemini video analysis and validated timestamped recommendations (implemented; live video analysis was not used for verification).
- Stage 3: draft clip editing and optional focal-point framing recommendations (implemented; approval and export are not included).
- Stage 4: local faster-whisper transcription and editable, render-compatible caption drafts (implemented; final FFmpeg/ASS rendering is intentionally deferred).
- Stage 5: rendered preview, explicit approval, immutable versioned exports, playback/download, and editing after export (implemented; visual matching still requires manual checks on the target Windows system).
- Split-Screen Streamer + Gameplay add-on after Stage 5: optional vertical same-video or custom-image composition integrated with Stage 5 preview/export (implemented; no face detection or batch workflow).

