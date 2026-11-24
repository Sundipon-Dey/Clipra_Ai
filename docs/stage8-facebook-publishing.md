# Stage 8: Facebook Page Reels publishing

CLIPRA can publish a completed export version as a Reel to a Facebook Page after the user connects Meta and explicitly approves each upload. It does not publish automatically. The current integration is for Facebook Pages, not personal timelines or Instagram.

## Meta app configuration

1. Create a Meta app with the **Manage everything on your Page** use case.
2. Keep the app in Development mode while testing with the app administrator/test roles.
3. In the use case permissions, enable `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, and `business_management`. CLIPRA first looks for Pages via `me/accounts`; for Pages owned by a Business Portfolio it also looks them up through `me/businesses` and the business's `owned_pages` edge.
4. Create a locally trusted development certificate for the HTTPS loopback callback. In PowerShell at the project root:

   ```powershell
   winget install --id FiloSottile.mkcert --exact
   # Close and reopen PowerShell after installation so mkcert is on PATH.
   mkcert -install
   New-Item -ItemType Directory -Force backend/secrets
   mkcert -cert-file backend/secrets/facebook-localhost.pem -key-file backend/secrets/facebook-localhost-key.pem localhost 127.0.0.1
   ```

   `mkcert -install` adds its local development CA to the current Windows user's trust store. Only use the official [mkcert project](https://github.com/FiloSottile/mkcert); do not share or commit its CA private key.

5. In the app's Facebook Login for Business OAuth settings, enable OAuth login and add this exact **Valid OAuth Redirect URI**:

   `https://localhost:8765/api/social/facebook/callback`

6. The Facebook account used during authorization must have Page access that permits creating content. CLIPRA discovers directly assigned Pages through `me/accounts` and Business Portfolio-owned Pages through the Business API.
7. App Review/Advanced Access may be needed before people who are not app roles can use the integration. Meta controls this requirement and can change it.

See Meta's [Business Login setup](https://developers.facebook.com/docs/facebook-business-extension/fbe/get-started/business-login/) and [Page Reels API](https://developers.facebook.com/docs/graph-api/reference/page/video_reels/).

## Local credential file

Save the Meta app values in this ignored local file:

`backend/secrets/facebook-app.json`

```json
{
  "app_id": "YOUR_META_APP_ID",
  "app_secret": "YOUR_META_APP_SECRET"
}
```

The default can be overridden using `FACEBOOK_APP_SECRETS_FILE` in `backend/.env`. The app secret stays in the backend and is never returned by an API. The certificate and key paths can be overridden using `FACEBOOK_TLS_CERT_FILE` and `FACEBOOK_TLS_KEY_FILE`.

## Connection and upload behavior

- **Connect Facebook** opens Meta OAuth in the system browser, uses a random state value and the fixed loopback callback, exchanges the authorization code, and retrieves Pages available to the authorized user.
- Page access tokens are stored with Windows DPAPI under the configured private workspace directory. The UI receives only Page IDs and names. Disconnect clears the local token file; it does not change Page roles or app settings.
- Publishing requires a completed export, a completed social-content generation for that exact export, saved Facebook Reels copy, a selected Page, and a separate explicit approval checkbox.
- The backend uses the Page Reels `START`, binary upload, and `FINISH` flow. Transfer progress is stored in SQLite. The source export and prior versions are not modified.
- An upload interrupted by app restart is marked interrupted and is not automatically retried. Check the Facebook Page before attempting another upload.

## Limitations and verification

The live Meta OAuth and publishing path requires the app's actual credentials, redirect configuration, Page access, and Meta's current permissions. Automated local checks cannot prove a real Page accepts the upload. A manual first test should use an export you are comfortable publishing, review the selected Page and caption, approve the upload explicitly, then confirm the Reel in that Page's Reels tab.
