# Stage 6: Social Media Content Generation

Stage 6 creates editable post copy for one completed export version. It does not publish videos, connect social accounts, process batches, transcribe clips, or change the video renderer.

## Generate content

1. Open a completed export version on the Export page and choose **Social content**.
2. Review the disclosure. For every generation, check the consent box to authorize sending that version's completed MP4 and its listed context to Google Gemini. Prior consent is not reused.
3. CLIPRA validates the immutable export path in managed storage, the MP4 extension, file size, and completed render status. The selected export is uploaded through Google's Files API and CLIPRA waits until its state is `ACTIVE`; the original source video is not substituted.
4. The configured `GEMINI_MODEL` receives the file reference and version-specific context through the SDK's `models.generate_content` call with a JSON response schema. Clipwing clips include their saved moment information and supplied URL/quote where available. Local uploads include the selected export's caption text where present. The original YouTube URL is context only; CLIPRA does not rely on Gemini to fetch it.
5. Review the TikTok, Instagram Reels, YouTube Shorts, and Facebook Reels packages. Edit and save text, copy a field or package, or explicitly generate another attempt.

Generation attempts and editable packages are saved against the exact export job. User edits are stored separately from the original generated package. A later generation creates another attempt and never replaces earlier text. Social copy is separate from captions/subtitles burned into the video.

## Gemini upload and privacy

The UI discloses that the completed MP4 and context go to Google and that quotas or charges may apply. Google free-tier data-use terms may permit submitted content to improve its products; review Google's current terms and pricing before consenting. The Files API upload is temporary and CLIPRA requests remote file/interaction cleanup after processing. Cleanup failures are retained as pending and surfaced in the generation status. Google documents a 48-hour Files API retention period if explicit cleanup fails.

The configured per-file ceiling is `GEMINI_FILE_MAX_BYTES` (2 GiB by default). An export over the ceiling is rejected without recompression, source substitution, or upload. Model and account quotas can change; no quota or cost guarantee is made. No automatic fallback model or automatic billable retry is performed.

## Recovery and local records

SQLite schema version 12 adds `social_content_generations`, which stores export association, consent timestamp, model/prompt version, source context, result/edit JSON, progress, sanitized errors, and Google cleanup references. Queued requests that have not started can resume after restart. Requests already uploading, processing, or generating are marked interrupted and are not repeated automatically. A user can start a new generation after reviewing the disclosure again.

The persistent job progress represents processing phases, not byte-level upload progress. Google GenAI's current SDK path does not expose reliable upload-byte progress to this UI.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/render-jobs/{render_job_id}/social-content-generations` | Start one consented generation for a completed export. |
| GET | `/api/render-jobs/{render_job_id}/social-content-generations` | List attempts and saved packages for that export version. |
| GET | `/api/social-content-generations/{generation_id}` | Read job progress and package state. |
| PATCH | `/api/social-content-generations/{generation_id}/platforms/{platform}` | Save edited content for one platform package. |

Automated tests mock Gemini and do not upload actual video content or make billable calls. A manual live generation requires explicit user consent and may consume quota or incur charges.
