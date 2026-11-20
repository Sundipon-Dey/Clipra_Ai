# Split-Screen Streamer + Gameplay

The optional split layout is part of the Stage 5 clip configuration. It renders to the existing 9:16, 1080 × 1920 profile and uses the same saved configuration for review previews and approved exports. The Original Layout remains the default and continues through its existing render filter.

## Editor behavior

- Choose **Split-Screen Streamer + Gameplay** in the clip editor. The top section can show the synchronized source video, a custom still image, or a solid color; the bottom section shows the source video.
- Select **Top · Streamer** or **Bottom · Gameplay** before changing section settings. Each section stores its own crop/fit mode, zoom, horizontal and vertical position, and fit background color. Top and bottom updates are separate values.
- Drag within a section in the preview to reposition that section. Drag the divider to change the top section's share of the output height (25–75%). Numeric position fields remain available.
- Captions render over the completed composition. For custom-image layouts, the source video's audio is the only audio stream mapped.
- The top solid-color option provides a color picker. Framing and zoom controls are hidden while this source is selected because there is no image content to frame.
- Switching back to Original Layout preserves the split configuration so it can be selected again later.

## Custom image safety and retention

Images are uploaded through the local API in bounded chunks. The backend checks the allowed PNG, JPEG, or WebP extension and matching file signature, enforces `CLIPRA_MAX_LAYOUT_IMAGE_BYTES` (25 MiB by default), probes dimensions, and decodes a frame before storing the file under `projects/<project-id>/layout-images/`. Each generated path is checked against the configured workspace before it is read.

Images receive immutable generated filenames and are never replaced in place. Changing the clip's selected image does not remove old files. There is no image deletion endpoint; in particular, preview generation, editing, export, and clip cleanup do not automatically remove managed custom images. This keeps assets available to saved layouts and immutable render snapshots/exports. Project data cleanup is an explicit future maintenance operation.

## Rendering and verification

The preview and final export renderer share the same FFmpeg filter graph for split composition, section framing, timing, caption overlay, and the single source audio stream. Preview encoding may use a faster preset and lower quality. Any clip edit changes the snapshot hash and makes an earlier preview ineligible for approval.

Caption exports follow the editor's current preset text/highlight colors and preset shadow, apply word highlighting and a pop to each spoken word over saved word timings, and ignore legacy outline width. The selected preset's cue-entry animation also remains applied. These word pops are consistent across all presets in the editor preview and rendered output. Caption position remains the saved track position.

Backend coverage is in `backend/tests/test_split_layout.py` and the Stage 5 render workflow tests. Run the backend suite from the repository root:

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest .\backend\tests -q
```

Run frontend tests and the production build:

```powershell
Push-Location .\frontend
npm.cmd test
npm.cmd run build
Pop-Location
```

Manual review should compare a generated Stage 5 preview with its approved export for divider placement, independent crop/fit/zoom/position behavior, caption placement/timing, synchronized same-video sections, custom image persistence, and audio. Automated tests use only generated synthetic media and do not establish visual equivalence on every Windows GPU/display configuration.
