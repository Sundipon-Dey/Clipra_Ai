import { useEffect, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Clapperboard, LoaderCircle, X } from 'lucide-react'
import { mediaUrl, requestPreview, type MediaAsset } from './api'

type Props = { media: MediaAsset; onClose: () => void; onMediaUpdated: (media: MediaAsset) => void; previewRange?: { startSeconds: number; endSeconds: number } | null }
type PreviewState = 'source' | 'preparing' | 'ready' | 'failed'

export default function MediaPlayer({ media, onClose, onMediaUpdated, previewRange }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [currentMedia, setCurrentMedia] = useState(media)
  const [previewState, setPreviewState] = useState<PreviewState>(media.preview_status === 'ready' ? 'source' : 'source')
  const [usingPreview, setUsingPreview] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)

  useEffect(() => {
    setCurrentMedia(media)
    setPreviewState('source')
    setUsingPreview(false)
    setPreviewError(null)
  }, [media.id])

  async function preparePreview() {
    if (previewState === 'preparing') return
    setPreviewState('preparing')
    setPreviewError(null)
    const preparingMedia = { ...currentMedia, preview_status: 'processing' as const, preview_error: null }
    setCurrentMedia(preparingMedia)
    onMediaUpdated(preparingMedia)
    try {
      const result = await requestPreview(currentMedia.id)
      setCurrentMedia(result.media)
      onMediaUpdated(result.media)
      setUsingPreview(true)
      setPreviewState('ready')
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Preview generation failed.'
      const failedMedia = { ...currentMedia, preview_status: 'failed' as const, preview_error: message }
      setCurrentMedia(failedMedia)
      onMediaUpdated(failedMedia)
      setPreviewError(message)
      setPreviewState('failed')
    }
  }

  function handleSourceError() {
    if (!usingPreview && previewState === 'source') void preparePreview()
    else if (usingPreview) {
      setPreviewError('The generated preview could not be played by this browser.')
      setPreviewState('failed')
    }
  }

  function seekToSuggestedRange() {
    const video = videoRef.current
    if (!video || !previewRange) return
    video.currentTime = previewRange.startSeconds
    void video.play().catch(() => undefined)
  }

  function stopAtSuggestedEnd() {
    const video = videoRef.current
    if (video && previewRange && video.currentTime >= previewRange.endSeconds) video.pause()
  }

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  const videoSource = usingPreview
    ? mediaUrl(currentMedia.preview_stream_url)
    : mediaUrl(currentMedia.stream_url)

  return (
    <div className="modal-backdrop player-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section className="player-modal" role="dialog" aria-modal="true" aria-labelledby="player-title">
        <header className="player-header">
          <div className="player-heading">
            <span className="player-icon"><Clapperboard size={18} /></span>
            <div><h2 id="player-title">Video preview</h2><p>{currentMedia.original_filename}</p></div>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close preview"><X size={19} /></button>
        </header>
        <div className="video-stage">
          <video
            key={`${currentMedia.id}-${usingPreview ? 'preview' : 'source'}`}
            ref={videoRef}
            src={videoSource}
            controls
            playsInline
            preload="metadata"
            onLoadedMetadata={seekToSuggestedRange}
            onTimeUpdate={stopAtSuggestedEnd}
            onError={handleSourceError}
          />
          {previewState === 'preparing' && (
            <div className="video-overlay-status"><LoaderCircle size={21} className="spin" /><span>Preparing a compatible playback copy…</span><small>The source video remains unchanged.</small></div>
          )}
          {previewState === 'failed' && (
            <div className="video-overlay-status error"><AlertCircle size={21} /><span>Preview unavailable</span><small>{previewError}</small><button className="button secondary small" onClick={() => void preparePreview()}>Retry preview</button></div>
          )}
        </div>
        <div className="player-footer">
          <div className="playback-state">
            {usingPreview ? <CheckCircle2 size={15} /> : <Clapperboard size={15} />}
            <span>{usingPreview ? 'Compatible playback copy · source unchanged' : 'Playing imported source'}</span>
          </div>
          {!usingPreview && previewState === 'source' && (
            <button className="text-button" onClick={() => void preparePreview()}>Prepare compatible preview</button>
          )}
          {usingPreview && <span className="preview-ready-label">Preview copy ready</span>}
          {previewRange && <span className="preview-ready-label">Suggested segment · {previewRange.startSeconds.toFixed(1)}–{previewRange.endSeconds.toFixed(1)}s</span>}
        </div>
      </section>
    </div>
  )
}
