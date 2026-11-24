# Stage 6: Social Media Content Generation

Stage 6 creates editable post copy for one completed export version. It does not publish videos, connect social accounts, process batches, transcribe clips, or change the video renderer.

## Generate content

1. Open a completed export version on the Export page and choose **Social content**.
2. Review the disclosure. For every generation, check the consent box to authorize sending that version's completed MP4 and its listed context to Google Gemini. Prior consent is not reused.
3. CLIPRA validates the immutable export path in managed storage, the MP4 extension, file size, and completed render status. The selected export is uploaded through Google's Files API and CLIPRA waits until its state is `ACTIVE`; the original source video is not substituted.
4. The configured `GEMINI_MODEL` receives the file reference and version-specific context through the SDK's `models.generate_content` call with a JSON response schema. Clipwing clips include their saved moment information and supplied URL/quote where available. Local uploads include the selected export's caption text where present. The original YouTube URL is context only; CLIPRA does not rely on Gemini to fetch it.
5. Review the Instagram Reels, YouTube Shorts, and Facebook Reels packages. Edit and save text, copy a field or package, or explicitly generate another attempt.

## Manual AI fallback

If a Gemini generation fails, choose **Copy prompt** to get the full export-specific prompt CLIPRA uses, including the saved context and exact four-platform JSON keys, field names, types, and limits. Attach the same completed export MP4 yourself in a video-capable AI chat and paste the returned JSON with **Paste output**. CLIPRA validates all four packages before importing them into that failed generation; an invalid or partial response leaves the failed attempt unchanged. The imported packages then use the normal review, edit, save, and publish-approval flow.

Copying the prompt does not upload the export or context to Google (or any other service). The user chooses whether and where to share the copied prompt and video. If Google file cleanup was pending on the failed attempt, manual import preserves that cleanup warning; it does not claim or perform remote cleanup.

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
| GET | `/api/social-content-generations/{generation_id}/manual-prompt` | Return the full version-specific prompt for manual AI fallback on a failed generation. |
| POST | `/api/social-content-generations/{generation_id}/manual-import` | Validate and import pasted AI output into that failed generation. |
| PATCH | `/api/social-content-generations/{generation_id}/platforms/{platform}` | Save edited content for one platform package. |

Automated tests mock Gemini and do not upload actual video content or make billable calls. A manual live generation requires explicit user consent and may consume quota or incur charges.
