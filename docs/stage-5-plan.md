# CLIPRA.AI Stage 5: Direct Export

## Approved scope

Stage 5 exports one edited clip at a time from its saved draft. The output profile is 9:16 at 1080 × 1920. The user explicitly approves by clicking **Export**. Each export is an immutable, versioned MP4; the draft stays editable after export.

## Implementation decisions

- The export request captures source identity, clip boundaries, framing, focal points, and the current boundary-valid caption track into one immutable render snapshot.
- Export uses the shared FFmpeg composition/framing pipeline and captions rendered by Chromium with the editor's `CaptionOverlay` component and CSS. There is no separate rendered preview pass.
- Approved exports use H.264 CRF 18 with the medium preset and AAC audio at 160 kb/s. Output remains 1080 × 1920.
- Each approved export receives a monotonically numbered V1, V2, and later version and a unique destination. Editing cannot modify an earlier export.
- Export history supports playback, download, and Reopen in Editor. Source videos and completed exports are never automatically deleted during normal editing or rendering.
- The workflow is single-clip only. There is no batch processing or aspect-ratio selector.

## Verification

- Backend tests cover explicit approval, direct immutable exports, version history, playback/download ranges, source preservation, split layouts, and Chromium caption composition using synthetic FFmpeg fixtures.
- Frontend tests cover the direct export workflow and production TypeScript/Vite builds.
- Manual Windows checks should compare the editor canvas with a fresh export on the target machine.

## Runtime requirements and retained data

- Caption rendering requires Node.js plus Microsoft Edge or Google Chrome installed. CLIPRA does not download a browser binary.
- Existing Stage 5 preview files and database rows from older builds are retained locally and hidden from the export workflow; new review previews are not generated.
- Imported-media compatibility previews remain available for browser playback when the source codec is unsupported. They are separate from Stage 5 clip rendering.
