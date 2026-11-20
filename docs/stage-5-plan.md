# CLIPRA.AI Stage 5: Preview, Approval, and Export

## Approved scope

Stage 5 completes one clip at a time from saved draft through rendered review, explicit approval, and versioned MP4 export. The default and only Stage 5 output profile is 9:16 at 1080 × 1920. Existing draft clips and captions remain editable after every export.

## Implementation decisions

- A render snapshot captures source identity, clip boundaries, framing settings and focal points, and the current boundary-valid caption track. Preview and export use the same FFmpeg filter graph and caption script. Preview may encode faster and at lower quality; it retains the export dimensions, crop, timing, style, and effects.
- A preview is eligible for approval only while the current persisted edit snapshot has the same SHA-256 configuration hash. Editing after preview makes it stale; export approval requires a newly rendered current preview.
- Approval is a separate explicit action. It creates an immutable export job from the reviewed preview snapshot. Export files use unique destinations and monotonically numbered V1, V2, … versions. Editing never changes an existing export.
- Completed previews and exports are managed workspace files, streamed with byte ranges. Exports support browser playback and download. The UI offers Reopen in Editor and export history.
- Source videos are read-only inputs. Normal editing, rendering, and exporting never delete originals or completed exports. Jobs survive process restarts: queued jobs resume, while processing jobs become interrupted and are not silently rerun.
- This is a single-clip flow. There is no batch processing or aspect-ratio selector.

## Verification plan

- Exercise the additive SQLite schema migration, job persistence, immutable snapshots, stale-preview rejection, approvals, V1/V2 history, range streaming, and source/export preservation with synthetic FFmpeg fixtures.
- Exercise the frontend workflow states and run all existing frontend tests plus the production TypeScript/Vite build.
- Run the full backend test suite. Perform manual Windows UI checks for captions/fonts and visual matching because installed fonts, FFmpeg builds, and video decoding vary by machine.

## Known constraints

- Caption burn-in requires the installed FFmpeg build to include libass (`subtitles` filter); requested fonts may be substituted by the operating system.
- Stage 5 exports H.264/AAC at 1080 × 1920. The preview uses the same geometry and filters but a faster preset and lower encoding quality.
- Smart Crop follows saved focal points. Unsupported caption CSS nuances are represented through the existing ASS-compatible style fields and animations.
