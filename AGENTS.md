# CLIPRA.AI project rules

## Product requirements
- Build a real, local-first Windows application for authorized video editing.
- Keep work staged. Do not start a later development stage until the current stage is implemented and verified.
- Do not replace required behavior with mock functionality or report simulated work as complete.
- Keep Gemini credentials on the backend. Never place secrets in frontend code, browser storage, logs, or generated assets.
- Never bypass DRM, sign-in, privacy, age, payment, or other access restrictions; never overwrite source media or automatically publish content. Clipwing import may fetch only a public YouTube URL explicitly pasted by the user after they confirm they have permission to download and edit it. Do not send account cookies or credentials to the downloader.
- Keep AI recommendations reviewable and require explicit user approval before rendering.
- Clearly disclose and require per-run confirmation before uploading a managed video copy to Gemini. A recommendation is never automatically approved or exported.

## Technical requirements
- Use Python 3.13 for the backend and the dedicated environment at `backend/.venv`.
- Keep backend APIs in FastAPI with validated Pydantic models; keep frontend and backend separated.
- Use safe subprocess argument lists for FFmpeg/FFprobe. Never build shell commands from user input.
- Store local project/job metadata in SQLite; keep credentials and generated/user media out of Git.
- Pin direct dependencies and commit the JavaScript lockfile.
- Stream video uploads in bounded chunks and enforce configurable per-file size limits.
- Copy user-selected source videos into a managed workspace. Never modify, move, overwrite, or automatically delete the user's original files.
- Generate previews as separate derived files. Validate every persisted media path inside the configured workspace before reading or writing it.
- Use FFprobe output for video metadata. Support HTTP byte ranges for playback and seeking.
- Use only the official `google-genai` Python SDK for Gemini. Read `GEMINI_API_KEY` and `GEMINI_MODEL` from backend environment configuration; never expose the key. Disable automatic retries for billable generation requests.
- Clipwing import parses user-pasted highlight results, performs one metadata/format lookup per video, and lets the user explicitly download each selected timestamp range as a managed H.264/AAC MP4 editable clip. Do not download the full source video for this flow. Do not bypass video access controls; no cookies or authentication are used. Stage 3 may create/edit unapproved draft clips and provide optional focal-point framing suggestions. Do not add clip approval or final rendering in Stage 3.
- Keep Smart Crop recommendations opt-in per request. Explain in the UI that a small set of selected still frames (not necessarily the full video) is sent to Google and may consume quota or incur charges. Never make Gemini necessary for the editor's manual framing functionality.
- Persist framing request states and focal points in SQLite. Do not automatically retry a request after failure/restart. Keep temporary extracted frames under managed temp storage and remove them after the request; validate all paths before I/O.
- Stage 3 clips remain drafts. Do not add clip approval, captions, or final rendering/export until the later planned stages.
- Keep Gemini uploads separate from local source storage. Use only validated managed workspace paths, enforce the configured Files API size ceiling, delete temporary remote files after analysis, and surface cleanup failures.
- Store Clipwing import jobs, format choices and entries in SQLite. Resume only queued metadata lookups on restart; mark active lookups and clip downloads interrupted and do not automatically repeat them. Keep direct signed media URLs in memory only. Retain old Gemini analysis rows only for compatibility and cleanup; do not expose or resume the removed Gemini highlight-analysis feature.
- Do not install faster-whisper before its planned stage or download AI models without an approved stage requirement.

## Workflow requirements
- Read the product specification and inspect existing files before changes.
- Work in small, verifiable stages and run the requested checks before proceeding.
- Use small synthetic FFmpeg-generated media fixtures for video tests; never use copyrighted samples.
- Explain Windows PowerShell setup/run commands in `README.md`.
- Update documentation when implementation behavior changes.
- At each stage boundary, report implementation, files, checks/results, remaining work, and the next stage.
