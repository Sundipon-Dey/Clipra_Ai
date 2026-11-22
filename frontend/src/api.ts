export type PreviewStatus = 'not_requested' | 'processing' | 'ready' | 'failed'

export type MediaAsset = {
  id: string
  project_id: string
  original_filename: string
  size_bytes: number
  duration_seconds: number
  width: number
  height: number
  frame_rate: string | null
  frame_rate_decimal: number | null
  video_codec: string
  audio_codec: string | null
  has_audio: boolean
  container_format: string
  preview_status: PreviewStatus
  preview_error: string | null
  imported_at: string
  stream_url: string
  preview_stream_url: string
}

export type Project = {
  id: string
  name: string
  created_at: string
  updated_at: string
  media_count: number
}

export type ProjectDetail = Project & { media: MediaAsset[] }
export type Health = { status: string; service: string; version: string; max_upload_bytes: string; max_files_per_import: string; gemini_configured: string; gemini_model: string; gemini_file_max_bytes: string }
export type ClipwingFormat = { format_id: string; label: string; width: number | null; height: number; ext: string; video_codec: string; audio_codec: string | null; fps: number | null; filesize_bytes: number | null }
export type ClipwingEntry = { id: string; ordinal: number; title: string; start_seconds: number; end_seconds: number; score: number | null; transcript: string | null; caption_source: 'none' | 'youtube'; selected_format_id: string | null; status: 'queued' | 'cutting' | 'ready' | 'failed' | 'interrupted'; progress: number; error_message: string | null; media_id: string | null; clip_id: string | null; video_url: string }
export type ClipwingImport = { id: string; project_id: string; status: 'queued' | 'downloading' | 'cutting' | 'completed' | 'completed_with_errors' | 'failed' | 'interrupted'; stage: string; progress: number; video_title: string | null; video_duration_seconds: number | null; formats: ClipwingFormat[]; error_message: string | null; created_at: string; updated_at: string; entries: ClipwingEntry[] }

export type FocalPoint = { time_seconds: number; x: number; y: number; confidence: number | null }
export type SplitSection = { source_mode?: 'same_video' | 'custom_image' | 'solid_color'; image_asset_id?: string | null; solid_color?: string; framing_mode: 'crop' | 'fit'; vertical_crop_percent?: number; zoom: number; position_x: number; position_y: number; fit_background_color: string }
export type SplitLayout = { split_ratio: number; top: SplitSection & { source_mode: 'same_video' | 'custom_image' | 'solid_color'; image_asset_id: string | null; solid_color: string }; bottom: SplitSection }
export type LayoutImage = { id: string; clip_id: string; original_filename: string; content_type: string; size_bytes: number; width: number; height: number; created_at: string; image_url: string }
export type CustomText = { enabled: boolean; text: string; preset_id: string; position_x: number; position_y: number; font_family: string; font_weight: number; font_size: number; text_color: string; background_color: string; background_opacity: number; animation: CaptionStyle['animation']; animation_ms: number; stroke_enabled: boolean; stroke_width: number; stroke_color: string; shadow_enabled: boolean; shadow_blur: number; shadow_color: string; shadow_x: number; shadow_y: number }
export type DraftClip = {
  id: string; project_id: string; media_id: string; source_candidate_id: string | null; title: string
  start_seconds: number; end_seconds: number; workflow_status: 'draft'
  framing_mode: 'smart_crop' | 'fit' | 'blurred_background' | 'manual_crop'
  recommended_framing_mode: string | null; manual_focus_x: number; manual_focus_y: number
  manual_zoom: number; vertical_crop_percent?: number; blur_strength: number; fit_background_color: string; framing_status: 'not_requested' | 'pending' | 'completed' | 'failed'
  manual_override_enabled: boolean
  layout_type: 'original' | 'split_streamer_gameplay'; split_layout: SplitLayout; custom_text?: CustomText
  framing_error_code: string | null; framing_error_message: string | null; framing_model: string | null
  framing_requested_at: string | null; framing_completed_at: string | null
  framing_start_seconds: number | null; framing_end_seconds: number | null
  created_at: string; updated_at: string; focal_points: FocalPoint[]
}

export type HardwareProfile = { cpu_count: number; memory_gib: number | null; free_disk_gib: number; recommendation_model: string; explanation: string }
export type TranscriptionModel = { id: string; display_name: string; language: string; estimated_download_mb: number; installed: boolean; recommended: boolean }
export type ModelDownload = { id: string; status: 'not_downloaded' | 'downloading' | 'installed' | 'failed'; error_message: string | null }
export type CaptionWord = { id: string; ordinal: number; start_seconds: number; end_seconds: number; original_text: string; text: string; confidence: number | null }
export type CaptionSegment = { id: string; ordinal: number; start_seconds: number; end_seconds: number; generated_text: string; override_text: string | null; manually_edited: boolean; words: CaptionWord[] }
export type CaptionStyle = { name: string; font_family: string; font_weight: number; font_size: number; text_color: string; highlight_color: string; outline_color: string; outline_width: number; shadow_color: string; shadow_offset: number; background_color: string; background_opacity: number; alignment: 'left' | 'center' | 'right'; animation: 'none' | 'fade' | 'pop' | 'karaoke' | 'pop_karaoke'; animation_ms: number }
export type CaptionTrack = { id: string; clip_id: string; transcription_run_id: string | null; name: string; language: string; preset_id: string; style_version: number; style: CaptionStyle; grouping: { max_words_per_line: number; max_lines: number; max_cue_seconds: number; pause_seconds: number; display_mode?: 'phrase' | 'one_word' }; position_x: number; position_y: number; safe_zone_profile: 'shorts' | 'reels' | 'tiktok' | 'facebook'; timing_offset_seconds: number; boundary_start_seconds: number; boundary_end_seconds: number; stale: boolean; created_at: string; updated_at: string; segments: CaptionSegment[] }
export type TranscriptionRun = { id: string; clip_id: string; media_id: string; status: string; model_id: string; language: string; device_profile: 'cpu:int8'; clip_start_seconds: number; clip_end_seconds: number; started_at: string | null; completed_at: string | null; error_code: string | null; error_message: string | null; created_at: string; caption_track_id: string | null }

export type RenderJob = { id: string; clip_id: string; project_id: string; kind: 'export'; status: 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled' | 'interrupted' | 'stale'; config_hash: string; progress: number; stage: string; error_message: string | null; output_bytes: number | null; version_number: number | null; approved_at: string | null; created_at: string; completed_at: string | null; stream_url: string | null; download_url: string | null; current: boolean; resolution: '1080' | '1440' }
export type SocialPlatform = 'tiktok' | 'instagram_reels' | 'youtube_shorts' | 'facebook_reels'
export type SocialPackage = Record<string, string | string[]>
export type SocialContentGeneration = { id: string; render_job_id: string; status: 'queued' | 'uploading' | 'processing_file' | 'generating' | 'completed' | 'failed' | 'interrupted'; progress: number; stage: string; model_name: string; prompt_version: string; error_code: string | null; error_message: string | null; cleanup_pending: boolean; created_at: string; completed_at: string | null; generated_packages: Record<SocialPlatform, SocialPackage> | null; packages: Record<SocialPlatform, SocialPackage> | null }
export type YouTubeStatus = { configured: boolean; connected: boolean; authorization_pending: boolean; message: string }
export type YouTubeUpload = { id: string; render_job_id: string; generation_id: string; status: 'queued' | 'uploading' | 'completed' | 'failed' | 'interrupted'; progress: number; stage: string; privacy_status: 'private' | 'unlisted' | 'public'; video_id: string | null; video_url: string | null; error_message: string | null; created_at: string; completed_at: string | null }

const apiBase = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')

export function mediaUrl(path: string) {
  return `${apiBase}${path}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, { cache: 'no-store', ...init })
  } catch {
    throw new Error('Could not reach the local CLIPRA.AI API. Make sure the backend is running.')
  }
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(typeof payload.detail === 'string' ? payload.detail : `Request failed with HTTP ${response.status}.`)
  }
  return payload as T
}

export const getProjects = () => request<Project[]>('/api/projects')

export const getProject = (id: string) => request<ProjectDetail>(`/api/projects/${encodeURIComponent(id)}`)

export const createProject = (name: string) =>
  request<Project>('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
export const deleteProject = (id: string) => request<void>(`/api/projects/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const startClipwingImport = (projectId: string, analysisText: string, confirmRights: boolean) => request<ClipwingImport>(`/api/projects/${encodeURIComponent(projectId)}/clipwing-imports`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ analysis_text: analysisText, confirm_rights: confirmRights }) })
export const getClipwingImports = (projectId: string) => request<ClipwingImport[]>(`/api/projects/${encodeURIComponent(projectId)}/clipwing-imports`)
export const getClipwingImport = (projectId: string, importId: string) => request<ClipwingImport>(`/api/projects/${encodeURIComponent(projectId)}/clipwing-imports/${encodeURIComponent(importId)}`)
export const downloadClipwingEntry = (projectId: string, importId: string, entryId: string, formatId: string) => request<ClipwingImport>(`/api/projects/${encodeURIComponent(projectId)}/clipwing-imports/${encodeURIComponent(importId)}/entries/${encodeURIComponent(entryId)}/download`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ format_id: formatId }) })
export const refreshClipwingDetails = (projectId: string, importId: string) => request<ClipwingImport>(`/api/projects/${encodeURIComponent(projectId)}/clipwing-imports/${encodeURIComponent(importId)}/refresh`, { method: 'POST' })

export function uploadVideo(projectId: string, file: File, onProgress: (progress: number) => void): Promise<MediaAsset> {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append('files', file, file.name)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${apiBase}/api/projects/${encodeURIComponent(projectId)}/media`)
    xhr.responseType = 'json'
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100))
    }
    xhr.onerror = () => reject(new Error('The upload connection was interrupted.'))
    xhr.onabort = () => reject(new Error('The upload was cancelled.'))
    xhr.onload = () => {
      const payload = xhr.response
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(payload?.detail ?? `Upload failed with HTTP ${xhr.status}.`))
        return
      }
      const failed = payload?.failed?.[0]
      if (failed) {
        reject(new Error(failed.error ?? 'This file could not be imported.'))
        return
      }
      const media = payload?.imported?.[0] as MediaAsset | undefined
      if (!media) {
        reject(new Error('The server did not return an imported media record.'))
        return
      }
      resolve(media)
    }
    xhr.send(form)
  })
}

export const requestPreview = (id: string) =>
  request<{ media: MediaAsset; message: string }>(`/api/media/${encodeURIComponent(id)}/preview`, { method: 'POST' })

export const getClips = (mediaId: string) => request<DraftClip[]>(`/api/media/${encodeURIComponent(mediaId)}/clips`)
export const getClip = (clipId: string) => request<DraftClip>(`/api/clips/${encodeURIComponent(clipId)}`)
export const deleteClip = (id: string) => request<void>(`/api/clips/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const createManualClip = (mediaId: string, title: string, startSeconds: number, endSeconds: number) =>
  request<DraftClip>(`/api/media/${encodeURIComponent(mediaId)}/clips`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title, start_seconds: startSeconds, end_seconds: endSeconds }) })
export const saveClip = (clip: DraftClip, fields: Partial<DraftClip>) =>
  request<DraftClip>(`/api/clips/${encodeURIComponent(clip.id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fields) })

export const layoutImageUrl = (id: string) => mediaUrl(`/api/layout-images/${encodeURIComponent(id)}`)
export async function uploadLayoutImage(clipId: string, file: File): Promise<LayoutImage> {
  const form = new FormData()
  form.append('file', file, file.name)
  return request<LayoutImage>(`/api/clips/${encodeURIComponent(clipId)}/layout-images`, { method: 'POST', body: form })
}
export const requestFramingSuggestion = (clipId: string, retry = false) =>
  request<DraftClip>(`/api/clips/${encodeURIComponent(clipId)}/framing-suggestion`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ consent_to_send_frames: true, retry }) })

export const getHardwareProfile = () => request<HardwareProfile>('/api/transcription/hardware-profile')
export const getTranscriptionModels = () => request<TranscriptionModel[]>('/api/transcription/models')
export const getModelDownload = (id: string) => request<ModelDownload>(`/api/transcription/models/${encodeURIComponent(id)}`)
export const downloadTranscriptionModel = (id: string) => request<ModelDownload>(`/api/transcription/models/${encodeURIComponent(id)}/download`, { method: 'POST' })
export const startTranscription = (clipId: string, modelId: string, start: number, end: number) => request<TranscriptionRun>(`/api/clips/${encodeURIComponent(clipId)}/transcriptions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model_id: modelId, language: 'en', start_seconds: start, end_seconds: end }) })
export const clearTranscriptions = (clipId: string) => request<void>(`/api/clips/${encodeURIComponent(clipId)}/transcriptions`, { method: 'DELETE' })
export const getTranscriptions = (clipId: string) => request<TranscriptionRun[]>(`/api/clips/${encodeURIComponent(clipId)}/transcriptions`)
export const getCaptionTracks = (clipId: string) => request<CaptionTrack[]>(`/api/clips/${encodeURIComponent(clipId)}/caption-tracks`)
export const createCaptionTrack = (clipId: string, presetId: string, name = 'Captions') => request<CaptionTrack>(`/api/clips/${encodeURIComponent(clipId)}/caption-tracks`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, preset_id: presetId }) })
export const updateCaptionTrack = (id: string, fields: Partial<CaptionTrack> & { style?: CaptionStyle }) => request<CaptionTrack>(`/api/caption-tracks/${encodeURIComponent(id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fields) })
export const updateCaptionWord = (id: string, text: string) => request<CaptionTrack>(`/api/caption-words/${encodeURIComponent(id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) })
export const reflowCaptionTrack = (id: string, maxWords: number, maxLines: number) => request<CaptionTrack>(`/api/caption-tracks/${encodeURIComponent(id)}/reflow`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ max_words_per_line: maxWords, max_lines: maxLines }) })

export const requestClipExport = (id: string, captionTrackId: string | null, resolution: '1080' | '1440') => request<RenderJob>(`/api/clips/${encodeURIComponent(id)}/exports`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ approved: true, caption_track_id: captionTrackId, resolution }) })
export const getRenderHistory = (id: string, captionTrackId: string | null) => request<RenderJob[]>(`/api/clips/${encodeURIComponent(id)}/render-jobs${captionTrackId ? `?caption_track_id=${encodeURIComponent(captionTrackId)}` : ''}`)
export const getRenderJob = (id: string) => request<RenderJob>(`/api/render-jobs/${encodeURIComponent(id)}`)
export const getSocialContentHistory = (renderJobId: string) => request<SocialContentGeneration[]>(`/api/render-jobs/${encodeURIComponent(renderJobId)}/social-content-generations`)
export const startSocialContentGeneration = (renderJobId: string) => request<SocialContentGeneration>(`/api/render-jobs/${encodeURIComponent(renderJobId)}/social-content-generations`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ consent_to_upload_video: true }) })
export const getSocialContentGeneration = (id: string) => request<SocialContentGeneration>(`/api/social-content-generations/${encodeURIComponent(id)}`)
export const saveSocialPackage = (id: string, platform: SocialPlatform, content: SocialPackage) => request<SocialContentGeneration>(`/api/social-content-generations/${encodeURIComponent(id)}/platforms/${platform}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }) })
export const getYouTubeStatus = () => request<YouTubeStatus>('/api/social/youtube/status')
export const connectYouTube = () => request<{ status: string; message: string }>('/api/social/youtube/connect', { method: 'POST' })
export const disconnectYouTube = () => request<YouTubeStatus>('/api/social/youtube/connection', { method: 'DELETE' })
export const getYouTubeUploads = (renderJobId: string) => request<YouTubeUpload[]>(`/api/social/youtube/exports/${encodeURIComponent(renderJobId)}/uploads`)
export const startYouTubeUpload = (renderJobId: string, generationId: string, privacyStatus: YouTubeUpload['privacy_status']) => request<YouTubeUpload>(`/api/social/youtube/exports/${encodeURIComponent(renderJobId)}/uploads`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ generation_id: generationId, privacy_status: privacyStatus }) })
export const getYouTubeUpload = (uploadId: string) => request<YouTubeUpload>(`/api/social/youtube/uploads/${encodeURIComponent(uploadId)}`)

