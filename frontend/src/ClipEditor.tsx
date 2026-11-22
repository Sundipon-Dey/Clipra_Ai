import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertCircle, ChevronDown, Crop, LoaderCircle, Play, Save, Volume2, VolumeX, X } from 'lucide-react'
import { getClip, layoutImageUrl, mediaUrl, requestPreview, saveClip, updateCaptionTrack, type CaptionTrack, type DraftClip, type LayoutImage, type MediaAsset, type SplitLayout } from './api'
import CaptionOverlay from './CaptionOverlay'
import CaptionPanel from './CaptionPanel'
import CustomTextOverlay from './CustomTextOverlay'
import ClipRenderWorkflow from './ClipRenderWorkflow'
import ClipRangeSelector from './ClipRangeSelector'
import SplitLayoutControls from './SplitLayoutControls'
import { DEFAULT_CUSTOM_TEXT } from './customText'
import { boundaryError, formatInputSeconds, formatTimestamp, type BoundaryKey, type ClipBounds } from './clipBoundaries'
import { clampSplitRatio, DEFAULT_SPLIT_LAYOUT, splitSectionHeights, splitSourceDrawRect, updateSectionPosition, type SplitSectionKey } from './splitLayout'

type Props = { media: MediaAsset; clip: DraftClip; geminiConfigured?: boolean; model?: string; onClose: () => void; onSaved: (clip: DraftClip) => void; onMediaUpdated: (media: MediaAsset) => void }
const modes = [
  ['fit', 'Fit / Original'], ['blurred_background', 'Blurred Background'], ['manual_crop', 'Manual Crop'],
] as const
const timeLabel = formatTimestamp

export default function ClipEditor({ media, clip: initial, onClose, onSaved, onMediaUpdated }: Props) {
  const [clip, setClip] = useState({ ...initial, framing_mode: (initial.framing_mode === 'smart_crop' ? 'manual_crop' : initial.framing_mode), custom_text: initial.custom_text ?? DEFAULT_CUSTOM_TEXT } as DraftClip)
  const [currentMedia, setCurrentMedia] = useState(media)
  const [usingPreview, setUsingPreview] = useState(false)
  const [previewState, setPreviewState] = useState<'source' | 'preparing' | 'failed'>('source')
  const [current, setCurrent] = useState(initial.start_seconds)
  const [startText, setStartText] = useState(formatInputSeconds(initial.start_seconds))
  const [endText, setEndText] = useState(formatInputSeconds(initial.end_seconds))
  const [boundaryMessage, setBoundaryMessage] = useState<string | null>(null)
  const [playing, setPlaying] = useState(false)
  const [audioEnabled, setAudioEnabled] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState('Saved draft')
  const manualOverride = Boolean(initial.manual_override_enabled)
  const [captionTrack, setCaptionTrack] = useState<CaptionTrack | null>(null)
  const [renderWorkflow, setRenderWorkflow] = useState(false)
  const [splitLayout, setSplitLayout] = useState<SplitLayout>(initial.split_layout ?? DEFAULT_SPLIT_LAYOUT)
  const [activeSplitSection, setActiveSplitSection] = useState<SplitSectionKey>('top')
  const [layoutImageRevision, setLayoutImageRevision] = useState(0)
  const layoutImageRefs = useRef<{ top: HTMLImageElement | null; bottom: HTMLImageElement | null }>({ top: null, bottom: null })
  const splitDragRef = useRef<{ kind: 'section' | 'divider'; section: SplitSectionKey; x: number; y: number; width: number; height: number; ratio: number; initial: SplitLayout } | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const boundaryInputError = boundaryError(startText, endText, media.duration_seconds)

  const update = (patch: Partial<DraftClip>) => {
    setClip((value) => ({ ...value, ...patch }))
    setSaveMessage('Unsaved changes')
  }

  const changeSplitLayout = (next: SplitLayout) => {
    setSplitLayout(next)
    update({ split_layout: next })
  }

  const onLayoutImageUploaded = (image: LayoutImage, section: SplitSectionKey) => {
    const next = section === 'top'
      ? { ...splitLayout, top: { ...splitLayout.top, source_mode: 'custom_image' as const, image_asset_id: image.id } }
      : { ...splitLayout, bottom: { ...splitLayout.bottom, source_mode: 'custom_image' as const, image_asset_id: image.id } }
    setSplitLayout(next)
    update({ split_layout: next })
  }

  useEffect(() => {
    let cancelled = false
    const ids = { top: splitLayout.top.image_asset_id, bottom: splitLayout.bottom.image_asset_id }
    let remaining = 2
    const done = () => { remaining -= 1; if (!cancelled && remaining === 0) setLayoutImageRevision((value) => value + 1) }
    const images: HTMLImageElement[] = []
    for (const section of ['top', 'bottom'] as const) {
      layoutImageRefs.current[section] = null
      const assetId = ids[section]
      if (!assetId) { done(); continue }
      const image = new Image()
      images.push(image)
      image.crossOrigin = 'anonymous'
      image.onload = () => { layoutImageRefs.current[section] = image; done() }
      image.onerror = () => { layoutImageRefs.current[section] = null; setSaveMessage('Saved custom image could not be loaded'); done() }
      image.src = layoutImageUrl(assetId)
    }
    return () => { cancelled = true; for (const image of images) { image.onload = null; image.onerror = null } }
  }, [splitLayout.top.image_asset_id, splitLayout.bottom.image_asset_id])

  const seek = useCallback((seconds: number) => {
    const video = videoRef.current
    if (!video || !Number.isFinite(seconds)) return
    const bounded = Math.max(0, Math.min(media.duration_seconds, seconds))
    video.currentTime = bounded
    setCurrent(bounded)
  }, [media.duration_seconds])

  const togglePlay = () => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) {
      if (video.currentTime < clip.start_seconds || video.currentTime >= clip.end_seconds) seek(clip.start_seconds)
      void video.play().then(() => setPlaying(true)).catch(() => setPlaying(false))
    } else {
      video.pause(); setPlaying(false)
    }
  }

  const preparePreview = async () => {
    if (previewState === 'preparing') return
    setPreviewState('preparing')
    try {
      const result = await requestPreview(currentMedia.id)
      setCurrentMedia(result.media); onMediaUpdated(result.media); setUsingPreview(true); setPreviewState('source')
    } catch { setPreviewState('failed') }
  }

  const persist = async () => {
    if (saving) return
    const validation = boundaryError(startText, endText, media.duration_seconds)
    if (validation) { setBoundaryMessage(validation); return }
    const start = Number(startText), end = Number(endText)
    setSaving(true)
    try {
      const saved = await saveClip(clip, {
        title: clip.title, start_seconds: start, end_seconds: end,
        framing_mode: clip.framing_mode, manual_focus_x: clip.manual_focus_x,
        manual_focus_y: clip.manual_focus_y, manual_zoom: clip.manual_zoom, vertical_crop_percent: clip.vertical_crop_percent ?? 0, blur_strength: clip.blur_strength,
        fit_background_color: clip.fit_background_color,
        manual_override_enabled: manualOverride,
        layout_type: clip.layout_type,
        split_layout: splitLayout,
        custom_text: clip.custom_text ?? DEFAULT_CUSTOM_TEXT,
      })
      setClip(saved); setSplitLayout(saved.split_layout); setStartText(formatInputSeconds(saved.start_seconds)); setEndText(formatInputSeconds(saved.end_seconds)); onSaved(saved); setSaveMessage('All changes saved')
      return true
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : 'Could not save changes')
      return false
    } finally { setSaving(false) }
  }

  useEffect(() => {
    let frame = -1
    let raf = 0
    const video = videoRef.current
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (!video || !canvas || !context) return
    const draw = () => {
      raf = requestAnimationFrame(draw)
      const width = video.videoWidth, height = video.videoHeight
      if (!width || !height || frame === video.currentTime) return
      frame = video.currentTime
      setCurrent(video.currentTime)
      if (video.currentTime >= clip.end_seconds) {
        video.pause(); video.currentTime = clip.end_seconds; setCurrent(clip.end_seconds); setPlaying(false)
      }
      const cw = canvas.width, ch = canvas.height
      context.clearRect(0, 0, cw, ch)
      if (clip.layout_type === 'split_streamer_gameplay') {
        const heights = splitSectionHeights(ch, splitLayout.split_ratio)
        const topSource = splitLayout.top.source_mode === 'custom_image' ? layoutImageRefs.current.top : splitLayout.top.source_mode === 'same_video' ? video : null
        const bottomMode = splitLayout.bottom.source_mode ?? 'same_video'
        const bottomSource = bottomMode === 'custom_image' ? layoutImageRefs.current.bottom : bottomMode === 'same_video' ? video : null
        drawSplitSection(context, topSource, 0, 0, cw, heights.top, splitLayout.top, splitLayout.top.source_mode === 'solid_color' ? splitLayout.top.solid_color : undefined)
        drawSplitSection(context, bottomSource, 0, heights.top, cw, heights.bottom, splitLayout.bottom, bottomMode === 'solid_color' ? splitLayout.bottom.solid_color : undefined)
        context.fillStyle = '#f1eeff'; context.fillRect(0, heights.top - 1, cw, 2)
        return
      }
      const mode = clip.framing_mode
      const cropY = height * ((clip.vertical_crop_percent ?? 0) / 100)
      const visibleHeight = Math.max(1, height - cropY * 2)
      const point = { x: clip.manual_focus_x, y: clip.manual_focus_y }
      if (mode === 'blurred_background') {
        const scale = Math.max(cw / width, ch / visibleHeight)
        const dw = width * scale, dh = visibleHeight * scale
        context.save(); context.filter = `blur(${clip.blur_strength}px)`
        context.drawImage(video, 0, cropY, width, visibleHeight, (cw - dw) / 2, (ch - dh) / 2, dw, dh); context.restore()
        const fit = Math.min(cw / width, ch / visibleHeight)
        const frontWidth = width * fit * clip.manual_zoom, frontHeight = visibleHeight * fit * clip.manual_zoom
        context.drawImage(video, 0, cropY, width, visibleHeight, (cw - frontWidth) / 2, (ch - frontHeight) / 2, frontWidth, frontHeight)
      } else if (mode === 'fit') {
        context.fillStyle = clip.fit_background_color; context.fillRect(0, 0, cw, ch)
        const fit = Math.min(cw / width, ch / visibleHeight)
        const frontWidth = width * fit * clip.manual_zoom, frontHeight = visibleHeight * fit * clip.manual_zoom
        context.drawImage(video, 0, cropY, width, visibleHeight, (cw - frontWidth) / 2, (ch - frontHeight) / 2, frontWidth, frontHeight)
      } else {
        const aspect = cw / ch
        let sw = Math.min(width, visibleHeight * aspect), sh = sw / aspect
        sw /= clip.manual_zoom; sh /= clip.manual_zoom
        const sx = Math.min(width - sw, Math.max(0, point.x * width - sw / 2))
        const sy = cropY + Math.min(visibleHeight - sh, Math.max(0, point.y * visibleHeight - sh / 2))
        context.drawImage(video, sx, sy, sw, sh, 0, 0, cw, ch)
      }
    }
    raf = requestAnimationFrame(draw)
    const onEnded = () => setPlaying(false)
    video.addEventListener('ended', onEnded)
    return () => { cancelAnimationFrame(raf); video.removeEventListener('ended', onEnded) }
  }, [clip, splitLayout, layoutImageRevision])

  const applyBounds = (bounds: ClipBounds, synchronizeText = false) => {
    update({ start_seconds: bounds.start, end_seconds: bounds.end })
    if (synchronizeText) {
      setStartText(formatInputSeconds(bounds.start))
      setEndText(formatInputSeconds(bounds.end))
    }
    setBoundaryMessage(null)
  }

  const setTimelineBounds = (bounds: ClipBounds) => applyBounds(bounds, true)

  const updateBoundaryText = (key: BoundaryKey, text: string) => {
    const nextStart = key === 'start_seconds' ? text : startText
    const nextEnd = key === 'end_seconds' ? text : endText
    key === 'start_seconds' ? setStartText(text) : setEndText(text)
    const validation = boundaryError(nextStart, nextEnd, media.duration_seconds)
    setBoundaryMessage(validation)
    if (!validation) applyBounds({ start: Number(nextStart), end: Number(nextEnd) })
  }

  const commitBoundaryText = () => {
    const validation = boundaryError(startText, endText, media.duration_seconds)
    if (validation) {
      setBoundaryMessage(validation)
      setStartText(formatInputSeconds(clip.start_seconds))
      setEndText(formatInputSeconds(clip.end_seconds))
      return
    }
    applyBounds({ start: Number(startText), end: Number(endText) }, true)
  }

  const setManualPoint = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (clip.layout_type !== 'original') return
    const video = videoRef.current
    if (!video?.videoWidth || !video.videoHeight) return
    const rect = event.currentTarget.getBoundingClientRect()
    const px = (event.clientX - rect.left) / rect.width, py = (event.clientY - rect.top) / rect.height
    let x: number, y: number
    const sourceCropY = video.videoHeight * ((clip.vertical_crop_percent ?? 0) / 100)
    const sourceVisibleHeight = video.videoHeight - sourceCropY * 2
    if (clip.framing_mode === 'fit' || clip.framing_mode === 'blurred_background') {
      const scale = Math.min(rect.width / video.videoWidth, rect.height / sourceVisibleHeight)
      x = (px * rect.width - (rect.width - video.videoWidth * scale * clip.manual_zoom) / 2) / (video.videoWidth * scale * clip.manual_zoom)
      y = (py * rect.height - (rect.height - sourceVisibleHeight * scale * clip.manual_zoom) / 2) / (scale * clip.manual_zoom * sourceVisibleHeight)
    } else {
      const ratio = 9 / 16
      const focal = { x: clip.manual_focus_x, y: clip.manual_focus_y }
      const cropWidth = Math.min(video.videoWidth, sourceVisibleHeight * ratio) / clip.manual_zoom
      const cropHeight = cropWidth / ratio
      const left = Math.min(video.videoWidth - cropWidth, Math.max(0, focal.x * video.videoWidth - cropWidth / 2))
      const top = sourceCropY + Math.min(sourceVisibleHeight - cropHeight, Math.max(0, focal.y * sourceVisibleHeight - cropHeight / 2))
      x = (left + px * cropWidth) / video.videoWidth
      y = (top - sourceCropY + py * cropHeight) / sourceVisibleHeight
    }
    update({ manual_focus_x: Math.max(0, Math.min(1, x)), manual_focus_y: Math.max(0, Math.min(1, y)) })
  }

  const beginSplitPositioning = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (clip.layout_type !== 'split_streamer_gameplay') return
    const rect = event.currentTarget.getBoundingClientRect()
    const y = event.clientY - rect.top
    const dividerY = rect.height * splitLayout.split_ratio
    const section: SplitSectionKey = y < dividerY ? 'top' : 'bottom'
    const kind = Math.abs(y - dividerY) <= 12 ? 'divider' : 'section'
    splitDragRef.current = { kind, section, x: event.clientX, y: event.clientY, width: rect.width, height: rect.height * (section === 'top' ? splitLayout.split_ratio : 1 - splitLayout.split_ratio), ratio: splitLayout.split_ratio, initial: splitLayout }
    if (kind === 'section') setActiveSplitSection(section)
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }

  const moveSplitPositioning = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const drag = splitDragRef.current
    if (!drag || clip.layout_type !== 'split_streamer_gameplay') return
    if (drag.kind === 'divider') {
      changeSplitLayout({ ...drag.initial, split_ratio: clampSplitRatio(drag.ratio + (event.clientY - drag.y) / Math.max(1, event.currentTarget.getBoundingClientRect().height)) })
      return
    }
    changeSplitLayout(updateSectionPosition(drag.initial, drag.section, event.clientX - drag.x, event.clientY - drag.y, drag.width, drag.height))
  }

  const setCaptionPosition = (x: number, y: number, commit: boolean) => {
    if (!captionTrack) return
    const next = { ...captionTrack, position_x: x, position_y: y }
    setCaptionTrack(next)
    if (!commit) return
    void updateCaptionTrack(next.id, { position_x: x, position_y: y })
      .then(setCaptionTrack)
      .catch((error) => setSaveMessage(error instanceof Error ? error.message : 'Caption position could not be saved.'))
  }

  if (renderWorkflow) return <ClipRenderWorkflow clip={clip} captionTrackId={captionTrack?.id ?? null} sourceWidth={media.width} sourceHeight={media.height} onEdit={() => { setRenderWorkflow(false); void getClip(clip.id).then((latest) => { setClip({ ...latest, framing_mode: latest.framing_mode === 'smart_crop' ? 'manual_crop' : latest.framing_mode, custom_text: latest.custom_text ?? DEFAULT_CUSTOM_TEXT }); setSplitLayout(latest.split_layout); setStartText(formatInputSeconds(latest.start_seconds)); setEndText(formatInputSeconds(latest.end_seconds)) }).catch(() => undefined) }}/>

  return <main className="clip-editor-backdrop clip-editor-page">
    <section className="clip-editor" aria-labelledby="clip-editor-title">
      <header className="clip-editor-header"><div><p className="eyebrow">DRAFT CLIP WORKSPACE</p><h2 id="clip-editor-title">Edit your clip</h2><span>{media.original_filename} · Draft · source video remains unchanged</span></div><div className="editor-header-actions"><button className="button secondary small" disabled={saving || Boolean(boundaryInputError)} onClick={() => void persist().then((saved) => { if (saved) setRenderWorkflow(true) })}>Export clip</button><button className="icon-button" onClick={onClose} aria-label="Close editor"><X size={18}/></button></div></header>
      <div className="clip-editor-grid">
        <section className="clip-controls-column clip-controls-left" aria-label="Clip settings" data-layout-type={clip.layout_type}>
          <label className="editor-field">Clip title<input value={clip.title} maxLength={160} onChange={(e) => update({ title: e.target.value })}/></label>
          <div className="boundary-controls"><label className="editor-field">Start (seconds)<input aria-label="Start (seconds)" aria-invalid={Boolean(boundaryInputError)} aria-describedby="clip-boundary-feedback" inputMode="decimal" type="text" value={startText} onFocus={(event) => event.currentTarget.select()} onChange={(event) => updateBoundaryText('start_seconds', event.target.value)} onBlur={commitBoundaryText} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur(); if (event.key === 'Escape') { setStartText(formatInputSeconds(clip.start_seconds)); setEndText(formatInputSeconds(clip.end_seconds)); setBoundaryMessage(null); event.currentTarget.blur() } }}/><small>{timeLabel(Number(startText) || 0)}</small></label><label className="editor-field">End (seconds)<input aria-label="End (seconds)" aria-invalid={Boolean(boundaryInputError)} aria-describedby="clip-boundary-feedback" inputMode="decimal" type="text" value={endText} onFocus={(event) => event.currentTarget.select()} onChange={(event) => updateBoundaryText('end_seconds', event.target.value)} onBlur={commitBoundaryText} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur(); if (event.key === 'Escape') { setStartText(formatInputSeconds(clip.start_seconds)); setEndText(formatInputSeconds(clip.end_seconds)); setBoundaryMessage(null); event.currentTarget.blur() } }}/><small>{timeLabel(Number(endText) || 0)}</small></label></div>
          <p id="clip-boundary-feedback" className={boundaryInputError || boundaryMessage ? 'boundary-feedback error' : 'boundary-feedback'} role={boundaryInputError || boundaryMessage ? 'alert' : undefined}>{boundaryInputError || boundaryMessage || `Enter seconds to three decimal places. Source duration: ${timeLabel(media.duration_seconds)}.`}</p>
          <div className="clip-duration"><span><Crop size={15}/> Clip duration</span><strong>{timeLabel(clip.end_seconds - clip.start_seconds)}</strong></div>
          <label className="editor-field layout-select-field">Layout<div className="layout-select-wrap"><select aria-label="Clip layout" value={clip.layout_type} onChange={(event) => update({ layout_type: event.target.value as DraftClip['layout_type'] })}><option value="original">Original Layout</option><option value="split_streamer_gameplay">Split-Screen Streamer + Gameplay</option></select><ChevronDown size={16} aria-hidden="true"/></div></label>
          {clip.layout_type === 'split_streamer_gameplay' && <div className="split-layout-section"><div className="framing-heading"><div><p className="eyebrow">SPLIT-SCREEN FRAMING</p><h3>Position each section</h3></div></div><SplitLayoutControls clipId={clip.id} value={splitLayout} active={activeSplitSection} onActive={setActiveSplitSection} onChange={changeSplitLayout} onImageUploaded={onLayoutImageUploaded}/></div>}
          <div className="framing-section"><div className="framing-heading"><div><p className="eyebrow">VERTICAL FRAMING</p><h3>Choose your composition</h3></div></div><div className="framing-options">{modes.map(([id, label]) => <button key={id} className={clip.framing_mode === id ? 'framing-option active' : 'framing-option'} onClick={() => update({ framing_mode: id })}>{label}</button>)}</div>
            {clip.framing_mode === 'manual_crop' && <>
              <label className="editor-field slider-field">Zoom <strong>{clip.manual_zoom.toFixed(2)}×</strong><input type="range" min="1" max="3" step="0.01" value={clip.manual_zoom} onChange={(e) => update({ manual_zoom: Number(e.target.value) })}/></label>
              <div className="focus-coordinates"><label>X <input type="number" min="0" max="1" step="0.01" value={clip.manual_focus_x.toFixed(2)} onChange={(e) => update({ manual_focus_x: Number(e.target.value) })}/></label><label>Y <input type="number" min="0" max="1" step="0.01" value={clip.manual_focus_y.toFixed(2)} onChange={(e) => update({ manual_focus_y: Number(e.target.value) })}/></label></div>
            </>}
              {(clip.framing_mode === 'blurred_background' || clip.framing_mode === 'fit') && <label className="editor-field slider-field">Zoom <strong>{clip.manual_zoom.toFixed(2)}×</strong><input aria-label="Original layout zoom" type="range" min="1" max="3" step="0.01" value={clip.manual_zoom} onChange={(e) => update({ manual_zoom: Number(e.target.value) })}/></label>}
              {clip.framing_mode === 'blurred_background' && <label className="editor-field slider-field">Background blur <strong>{clip.blur_strength}px</strong><input type="range" min="0" max="40" step="1" value={clip.blur_strength} onChange={(e) => update({ blur_strength: Number(e.target.value) })}/></label>}
              {clip.framing_mode === 'fit' && <label className="editor-field">Fit background color<div className="color-picker-row"><span className="color-picker-swatch" style={{ backgroundColor: clip.fit_background_color }} aria-hidden="true"/><span className="color-picker-value"><strong>{clip.fit_background_color.toUpperCase()}</strong><small>Preview background</small></span><input aria-label="Fit background color" type="color" value={clip.fit_background_color} onChange={(e) => update({ fit_background_color: e.target.value })}/></div></label>}
            {clip.layout_type === 'original' && <label className="editor-field slider-field">Trim top and bottom <strong>{(clip.vertical_crop_percent ?? 0).toFixed(1)}% each</strong><input aria-label="Vertical crop" type="range" min="0" max="40" step="0.5" value={clip.vertical_crop_percent ?? 0} onChange={(e) => update({ vertical_crop_percent: Number(e.target.value) })}/></label>}
          </div>
        </section>
        <section className="clip-preview-column">
          <div className={`vertical-preview ${clip.layout_type === 'split_streamer_gameplay' ? 'split-layout-preview' : ''}`}><canvas ref={canvasRef} width={360} height={640} onClick={setManualPoint} onPointerDown={beginSplitPositioning} onPointerMove={moveSplitPositioning} onPointerUp={() => { splitDragRef.current = null }} onPointerCancel={() => { splitDragRef.current = null }} title={clip.layout_type === 'original' ? 'Click to set the manual focal point' : 'Drag within the top or bottom section to reposition it'}/><CaptionOverlay track={captionTrack} clipStart={clip.start_seconds} currentSourceTime={current} editing onPosition={setCaptionPosition} canvasPassthrough={clip.layout_type === 'split_streamer_gameplay'}/><CustomTextOverlay value={clip.custom_text ?? DEFAULT_CUSTOM_TEXT} editing onChange={(patch) => update({ custom_text: { ...(clip.custom_text ?? DEFAULT_CUSTOM_TEXT), ...patch } })}/><span className="canvas-label">{clip.layout_type === 'original' ? '9:16 PREVIEW · CLICK TO SET FOCAL POINT' : 'DRAG TOP OR BOTTOM TO REPOSITION · DRAG DIVIDER TO RESIZE'}</span></div>
          <video key={`${media.id}-${usingPreview}`} ref={videoRef} src={mediaUrl(usingPreview ? currentMedia.preview_stream_url : currentMedia.stream_url)} preload="metadata" muted={!audioEnabled} playsInline onLoadedMetadata={(e) => { e.currentTarget.currentTime = current }} onError={() => { if (!usingPreview && previewState === 'source') void preparePreview(); else if (usingPreview) setPreviewState('failed') }} onTimeUpdate={(e) => { const time = e.currentTarget.currentTime; setCurrent(time); if (time >= clip.end_seconds) { e.currentTarget.pause(); e.currentTarget.currentTime = clip.end_seconds; setPlaying(false) } }} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} className="editor-source-video" />
          {previewState === 'preparing' && <div className="editor-preview-notice"><LoaderCircle size={14} className="spin"/> Preparing compatible preview…</div>}
          {previewState === 'failed' && <div className="editor-preview-notice error"><AlertCircle size={14}/> Preview could not be played. <button className="text-button" onClick={() => void preparePreview()}>Retry</button></div>}
          <div className="preview-controls"><button className="button secondary small" onClick={togglePlay}>{playing ? 'Pause' : <><Play size={13}/> Play clip</>}</button><button className="button secondary small" aria-label={audioEnabled ? 'Mute preview audio' : 'Enable preview audio'} aria-pressed={audioEnabled} onClick={() => setAudioEnabled((value) => !value)}>{audioEnabled ? <><Volume2 size={14}/> Audio on</> : <><VolumeX size={14}/> Audio off</>}</button><strong>{timeLabel(current)}</strong><span>of {timeLabel(media.duration_seconds)}</span></div>
          <div className="timeline"><ClipRangeSelector duration={media.duration_seconds} bounds={{ start: clip.start_seconds, end: clip.end_seconds }} currentTime={current} onBoundsChange={setTimelineBounds}/><input aria-label="Seek source video" type="range" min="0" max={media.duration_seconds} step="0.01" value={Math.min(current, media.duration_seconds)} onChange={(e) => seek(Number(e.target.value))}/><div className="timeline-labels"><span>0:00</span><span>Selected {timeLabel(clip.end_seconds - clip.start_seconds)}</span><span>{timeLabel(media.duration_seconds)}</span></div></div>
        </section>
        <section className="clip-controls-column clip-controls-right" aria-label="Recommendations and captions">
          <CaptionPanel clip={clip} activeTrack={captionTrack} onTrack={setCaptionTrack} customText={clip.custom_text ?? DEFAULT_CUSTOM_TEXT} onCustomText={(patch) => update({ custom_text: { ...(clip.custom_text ?? DEFAULT_CUSTOM_TEXT), ...patch } })}/>
          <div className="editor-save-row"><span className={saveMessage === 'Unsaved changes' ? 'save-status dirty' : 'save-status'}>{saveMessage}</span><button className="button primary" disabled={saving || Boolean(boundaryInputError) || !clip.title.trim()} onClick={() => void persist()}>{saving ? <><LoaderCircle size={15} className="spin"/> Saving…</> : <><Save size={15}/> Save draft</>}</button></div>
        </section>
      </div>
    </section>
  </main>
}

function drawSplitSection(context: CanvasRenderingContext2D, source: HTMLVideoElement | HTMLImageElement | null, x: number, y: number, width: number, height: number, section: SplitLayout['top'] | SplitLayout['bottom'], solidColor?: string) {
  context.save()
  context.beginPath(); context.rect(x, y, width, height); context.clip()
  context.fillStyle = section.fit_background_color; context.fillRect(x, y, width, height)
  if (solidColor) { context.fillStyle = solidColor; context.fillRect(x, y, width, height); context.restore(); return }
  const sourceWidth = source instanceof HTMLVideoElement ? source.videoWidth : source?.naturalWidth ?? 0
  const sourceHeight = source instanceof HTMLVideoElement ? source.videoHeight : source?.naturalHeight ?? 0
  if (!source || sourceWidth <= 0 || sourceHeight <= 0) { context.restore(); return }
  const cropTop = sourceHeight * ((section.vertical_crop_percent ?? 0) / 100)
  const visibleHeight = Math.max(1, sourceHeight - cropTop * 2)
  const rect = splitSourceDrawRect(sourceWidth, visibleHeight, width, height, section)
  context.drawImage(source, 0, cropTop, sourceWidth, visibleHeight, x + rect.x, y + rect.y, rect.width, rect.height)
  context.restore()
}
