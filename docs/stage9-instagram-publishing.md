# Stage 9: Instagram Reels publishing

CLIPRA publishes a completed export as a Reel to an Instagram Business or Creator account after the user connects Meta and explicitly approves each publication. Instagram uses the Graph API v25.0 `video_url` flow and Cloudflare R2 as temporary hosting. Facebook and YouTube upload behavior is separate and unchanged.

## Meta setup

1. In the existing CLIPRA Meta app, add **Manage messaging & content on Instagram**.
2. Both platform connections request `business_management` so CLIPRA can find Pages owned by a Business Portfolio. Facebook also requests `pages_show_list`, `pages_read_engagement`, and `pages_manage_posts`. Instagram adds `instagram_basic` and `instagram_content_publish`.
3. The Instagram profile must be Business or Creator and linked to a Facebook Page. CLIPRA discovers the linked account when Meta is authorized again.
4. Keep the app in Development mode for testing with an app administrator/developer/tester account. App Review / Advanced Access is required before accounts outside the app roles can use the requested permissions.
5. Keep the existing OAuth callback URI from Stage 8: `https://localhost:8765/api/social/facebook/callback`.
6. No new Meta secret file is needed. The integration uses `backend/secrets/facebook-app.json`, the existing trusted localhost certificate, and the encrypted Page-token store.

## Cloudflare R2 setup

Set these backend-only values in `backend/.env`:

```dotenv
R2_ACCOUNT_ID=your_cloudflare_account_id
R2_BUCKET=clipra-ai
R2_ACCESS_KEY_ID=your_r2_access_key_id
R2_SECRET_ACCESS_KEY=your_r2_secret_access_key
```

Create an R2 lifecycle rule that deletes objects under the exact `ig-reels/` prefix after one day. CLIPRA uses the S3-compatible endpoint `https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com`, signing region `auto`, and `Content-Type: video/mp4`. Run this PowerShell check after configuring R2 and restarting the backend:

```powershell
& .\backend\.venv\Scripts\python.exe .\backend\scripts\check_instagram_r2.py
```

It uploads a tiny disposable object to `ig-reels/`, creates two-hour presigned GET and HEAD URLs, prints only the GET URL location with its signed query redacted, performs the no-redirect HEAD verification using the HEAD-specific signature, and deletes the object. It does not contact Meta. A successful HEAD must return HTTP 200, `Content-Type: video/mp4`, and the exact uploaded `Content-Length`.

## Publishing behavior

- In the Instagram section, select the professional account, review and save the package, check the explicit approval box, then choose **Publish export Vn to Instagram**.
- CLIPRA validates the exact completed MP4 export, uploads it to a UUID object at `ig-reels/<uuid>.mp4`, creates two-hour presigned GET and HEAD URLs for that same object, and verifies the HEAD URL before sending the GET URL to Meta. SigV4 signatures authorize a specific HTTP method, so a GET-signed URL cannot be probed with HEAD. It never changes the source or export.
- CLIPRA creates the Reel container with `POST /v25.0/{ig_user_id}/media` using `media_type=REELS` and `video_url`. It stores the returned Meta container ID, polls `status_code,status` about every 30 seconds for up to 20 minutes, and calls `media_publish` only after `FINISHED`.
- `ERROR` and `EXPIRED` stop immediately. CLIPRA does not retry or reuse a failed container. A new user-approved attempt creates a new container.
- On successful publication or a known terminal failure, CLIPRA attempts to delete the temporary R2 object. It never deletes while the container may still be `IN_PROGRESS`. If processing times out or the state is uncertain, the object is retained and the one-day lifecycle rule removes it. R2 cleanup failures are logged and do not change the publication outcome.
- Every Meta response logs the endpoint, HTTP status, elapsed time, `x-fb-trace-id`, and response body. Access tokens and presigned URL query signatures are redacted. Meta error bodies are also surfaced in upload history and the UI.
- Instagram requests use Graph API v25.0 independently of `FACEBOOK_GRAPH_API_VERSION`; Facebook publishing remains on its existing configuration and resumable upload path.
- Instagram captions are limited to 2,200 characters. CLIPRA combines the saved caption (or opening hook when the caption is blank) with up to 30 saved hashtags.
- CLIPRA stores per-export progress, Meta container ID, and publication history in SQLite. Completed posts include an Instagram permalink when Meta returns one. Source clips, exports, and prior versions are not changed or deleted.

## API

- `GET /api/social/instagram/status` — Meta connection, linked Instagram accounts, and whether all R2 settings are configured (no credentials are returned).
- `POST /api/social/instagram/connect` — start the shared Meta OAuth flow.
- `POST /api/social/instagram/exports/{render_job_id}/uploads` — require `approved: true`, a completed generation for that exact export, a linked Instagram account, and configured R2 credentials.
- `GET /api/social/instagram/exports/{render_job_id}/uploads` — list publication status for the export.
- `GET /api/social/instagram/uploads/{upload_id}` — inspect one publication, including its Meta container ID and sanitized error body.

Automated checks mock R2 and Meta. A real publication needs the user's configured R2 bucket, Meta app, permissions, Page link, token authorization, and an export that meets Meta's current Reel rules.

## References

- [Meta Instagram Content Publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing)
- [Meta Instagram API video publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing)
- [Meta Instagram User requirements](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/v21.0/)
