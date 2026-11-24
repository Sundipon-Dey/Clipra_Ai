# Stage 7: YouTube publishing

Stage 7 adds a real YouTube upload path for one completed Stage 5 export. It uses the reviewed and saved **YouTube Shorts** package for that exact export version. Instagram and Facebook remain copy-only in this stage.

## One-time local setup

1. Keep the Google Auth Platform audience in **Testing** and keep the YouTube channel manager account in **Test users** while developing.
2. In **Data Access**, declare only `https://www.googleapis.com/auth/youtube.upload`. CLIPRA requests this narrow upload scope during account connection.
3. Copy the downloaded **Desktop app** OAuth JSON to `backend/secrets/youtube-oauth-client.json`. This directory is excluded from Git. Alternatively set `YOUTUBE_CLIENT_SECRETS_FILE` in `backend/.env` to the JSON file's absolute path.
4. Restart the backend after changing the credential file or environment path.
5. In Social Content, select **YouTube Shorts** and click **Connect YouTube**. Google opens in the system browser; sign into the Google account that manages the channel and approve the request. CLIPRA uses PKCE and a random `127.0.0.1` callback port.

Google's External OAuth apps in Testing have test-user restrictions and Google currently documents that their refresh tokens expire after seven days for scopes beyond basic profile access. Reconnect when Google reports an expired authorization. Keep the app in Testing for personal development; publishing or distributing the app may require Google's verification and completed branding details. See [Google OAuth token behavior](https://developers.google.com/identity/protocols/oauth2/) and [OAuth verification setup](https://support.google.com/cloud/answer/13461325).

## Upload workflow

1. Generate or select the social-content generation for a completed export.
2. Select **YouTube Shorts**. Review and save the title, description, hashtags, and tags.
3. Choose **Private** (default), **Unlisted**, or **Public**.
4. Check the per-upload approval box and click **Upload export Vn to YouTube**.
5. Watch chunk-level upload progress. On success, use the link to open the uploaded video in YouTube.

CLIPRA uploads the immutable completed MP4 as-is using YouTube's resumable `videos.insert` upload flow. It does not change the editor draft or the export file. Hashtags are appended to the saved description if missing, and tags plus hashtags are sent as YouTube tags. YouTube may need time to process the uploaded video before it is playable. The selected privacy is passed explicitly; CLIPRA never defaults the request to Public.

OAuth refresh tokens are encrypted with Windows DPAPI for the current Windows user and stored at `private/youtube/oauth-token.dpapi` under `CLIPRA_WORKSPACE_DIR` (or the repository workspace by default). The OAuth JSON and token directory are ignored by Git. **Disconnect** asks Google to revoke the token and removes the local token file.

Uploads are persisted in SQLite and serialized through one local upload worker. A restart marks queued or active uploads as interrupted; CLIPRA does not automatically re-send them. Network failures can happen after Google has accepted the last chunk but before CLIPRA receives confirmation. Check YouTube Studio before explicitly retrying an interrupted or uncertain upload to avoid creating a duplicate.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/social/youtube/status` | Report OAuth client configuration and local connection state. |
| POST | `/api/social/youtube/connect` | Start Google Desktop OAuth in the system browser. |
| DELETE | `/api/social/youtube/connection` | Revoke and remove the saved local authorization. |
| POST | `/api/social/youtube/exports/{render_job_id}/uploads` | Start an explicitly approved upload for a saved package and visibility. |
| GET | `/api/social/youtube/exports/{render_job_id}/uploads` | Read upload history for one immutable export. |
| GET | `/api/social/youtube/uploads/{upload_id}` | Read upload progress and result. |

## Limits and verification

This is a single-video flow. It uploads completed MP4 exports only, does not create thumbnails or schedule publishing, and does not post generated copy to other platforms. Upload success was not verified against the user's live Google account in development; first real use requires the local OAuth JSON, Google scope declaration, working internet, YouTube API quota, and explicit account consent. Google can reject a particular video, account, metadata, or API request; inspect the displayed error and YouTube Studio before trying again.
