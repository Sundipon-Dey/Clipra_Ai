import { useEffect, useState } from 'react'
import { Download, LoaderCircle, RefreshCw, Sparkles, Type } from 'lucide-react'
import { clearTranscriptions, createCaptionTrack, downloadTranscriptionModel, getCaptionTracks, getHardwareProfile, getModelDownload, getTranscriptionModels, getTranscriptions, reflowCaptionTrack, startTranscription, updateCaptionTrack, updateCaptionWord, type CaptionTrack, type DraftClip, type HardwareProfile, type TranscriptionModel, type TranscriptionRun } from './api'
import { captionPresets } from './captionPresets'

type Props = { clip: DraftClip; activeTrack: CaptionTrack | null; onTrack: (track: CaptionTrack | null) => void }

export default function CaptionPanel({ clip, activeTrack, onTrack }: Props) {
  const [hardware, setHardware] = useState<HardwareProfile | null>(null)
  const [models, setModels] = useState<TranscriptionModel[]>([])
  const [runs, setRuns] = useState<TranscriptionRun[]>([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const refresh = async () => {
    try {
      const [profile, modelList, history, tracks] = await Promise.all([getHardwareProfile(), getTranscriptionModels(), getTranscriptions(clip.id), getCaptionTracks(clip.id)])
      setHardware(profile); setModels(modelList); setRuns(history)
      if (!activeTrack && tracks[0]) onTrack(tracks[0])
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Caption services are unavailable.') }
    finally { setLoading(false) }
  }
  useEffect(() => { void refresh() }, [clip.id])
  useEffect(() => {
    if (!runs.some((run) => ['queued', 'extracting', 'transcribing'].includes(run.status))) return
    const id = window.setTimeout(() => void refresh(), 1400)
    return () => window.clearTimeout(id)
  }, [runs])
  const recommended = models.find((model) => model.recommended) ?? models[0]
  const selectedModel = recommended
  const download = async () => {
    if (!selectedModel) return
    setBusy(true); setMessage(null)
    try {
      await downloadTranscriptionModel(selectedModel.id)
      const poll = async () => {
        const status = await getModelDownload(selectedModel.id)
        if (status.status === 'downloading') { window.setTimeout(() => void poll(), 1500); return }
        await refresh(); if (status.status === 'failed') setMessage(status.error_message)
      }
      void poll()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Model download could not start.') }
    finally { setBusy(false) }
  }
  const transcribe = async () => {
    if (!selectedModel || !hardware) return
    setBusy(true); setMessage(null)
    try { const run = await startTranscription(clip.id, selectedModel.id, clip.start_seconds, clip.end_seconds); setRuns((runs) => [run, ...runs]) }
    catch (error) { setMessage(error instanceof Error ? error.message : 'Local transcription could not start.') }
    finally { setBusy(false) }
  }
  const clear = async () => { setBusy(true); try { await clearTranscriptions(clip.id); setRuns([]); onTrack(null); setMessage('Previous transcription and generated captions cleared.') } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not clear transcription.') } finally { setBusy(false) } }
  const createManual = async (presetId: string) => {
    setBusy(true)
    try { onTrack(await createCaptionTrack(clip.id, presetId)) } catch (error) { setMessage(error instanceof Error ? error.message : 'Caption track could not be created.') } finally { setBusy(false) }
  }
  const applyPreset = async (presetId: string) => {
    if (!activeTrack) return
    try { onTrack(await updateCaptionTrack(activeTrack.id, { preset_id: presetId })) } catch (error) { setMessage(error instanceof Error ? error.message : 'Preset could not be applied.') }
  }
  const saveStyle = async (key: keyof CaptionTrack['style'], value: string | number) => {
    if (!activeTrack) return
    try { onTrack(await updateCaptionTrack(activeTrack.id, { style: { ...activeTrack.style, [key]: value } })) } catch (error) { setMessage(error instanceof Error ? error.message : 'Caption style could not be saved.') }
  }
  return <section className="caption-panel">
    <div className="caption-heading"><div><p className="eyebrow">LOCAL CAPTIONS</p><h3><Type size={16}/> Captions & subtitles</h3></div><button className="icon-button subtle" onClick={() => void refresh()} aria-label="Refresh caption status"><RefreshCw size={14}/></button></div>
    {loading ? <p className="caption-note"><LoaderCircle size={13} className="spin"/> Checking local transcription tools…</p> : <>
      {hardware && <div className="hardware-card"><strong>{hardware.cpu_count}-thread CPU · INT8</strong><p>{hardware.explanation}</p><small>{hardware.memory_gib ? `${hardware.memory_gib} GB RAM · ` : ''}{hardware.free_disk_gib} GB workspace free · CPU INT8 transcription may take longer.</small></div>}
      {selectedModel && <div className="model-card"><div><strong>{selectedModel.display_name}</strong><small>{selectedModel.estimated_download_mb} MB · {selectedModel.language}</small></div>{selectedModel.installed ? <button className="button ai-button small" disabled={busy} onClick={() => void transcribe()}><Sparkles size={13}/> Transcribe clip locally</button> : <button className="button secondary small" disabled={busy} onClick={() => void download()}><Download size={13}/> Download model</button>}</div>}
      <p className="caption-note">Models download only after you choose Download. Transcription processes this clip locally; Gemini is not used.</p>
      {runs[0] && <p className={`caption-run ${runs[0].status}`}>{['queued', 'extracting', 'transcribing'].includes(runs[0].status) ? <LoaderCircle size={13} className="spin"/> : null}{runs[0].status === 'completed' ? 'Caption track generated locally.' : runs[0].error_message ?? `Transcription ${runs[0].status}.`}</p>}
      {runs.length > 0 && <button className="button secondary small" disabled={busy || runs.some((run) => ['queued','extracting','transcribing'].includes(run.status))} onClick={() => void clear()}>Clear transcription results</button>}
      <div className="preset-grid">{Object.entries(captionPresets).map(([id, style]) => <button key={id} className={activeTrack?.preset_id === id ? 'caption-preset active' : 'caption-preset'} onClick={() => activeTrack ? void applyPreset(id) : void createManual(id)}><strong>{style.name}</strong><small>{style.animation.replace('_', ' ')}</small></button>)}</div>
      {activeTrack && <div className="caption-edit-controls"><p className="caption-track-state">{activeTrack.stale ? 'Caption timing belongs to earlier clip boundaries. Review before using it.' : 'Caption track synced to current clip boundaries.'}</p><fieldset className="caption-display-mode"><legend>Text display</legend><div><button type="button" className={(activeTrack.grouping.display_mode ?? 'phrase') === 'phrase' ? 'active' : ''} aria-pressed={(activeTrack.grouping.display_mode ?? 'phrase') === 'phrase'} onClick={() => void updateCaptionTrack(activeTrack.id, { grouping: { ...activeTrack.grouping, display_mode: 'phrase' } }).then(onTrack).catch((error) => setMessage(error.message))}>Phrase</button><button type="button" className={activeTrack.grouping.display_mode === 'one_word' ? 'active' : ''} aria-pressed={activeTrack.grouping.display_mode === 'one_word'} onClick={() => void updateCaptionTrack(activeTrack.id, { grouping: { ...activeTrack.grouping, display_mode: 'one_word' } }).then(onTrack).catch((error) => setMessage(error.message))}>One word</button></div><small>{activeTrack.grouping.display_mode === 'one_word' ? 'Shows only the word currently being spoken.' : 'Shows the full phrase and highlights the spoken word.'}</small></fieldset><div className="caption-control-grid"><label>Size<input type="range" min="18" max="160" value={activeTrack.style.font_size} onChange={(e) => void saveStyle('font_size', Number(e.target.value))}/></label><label>Text<input type="color" value={activeTrack.style.text_color} onChange={(e) => void saveStyle('text_color', e.target.value)}/></label><label>Highlight<input type="color" value={activeTrack.style.highlight_color} onChange={(e) => void saveStyle('highlight_color', e.target.value)}/></label><label>Text background<select value={activeTrack.style.background_opacity === 0 ? 'none' : activeTrack.style.background_color.toLowerCase() === '#ffffff' ? 'white' : 'black'} onChange={(e) => { const value = e.target.value; void updateCaptionTrack(activeTrack.id, { style: { ...activeTrack.style, background_color: value === 'white' ? '#FFFFFF' : '#000000', background_opacity: value === 'none' ? 0 : 1 } }).then(onTrack).catch((error) => setMessage(error.message)) }}><option value="none">No background</option><option value="black">Black</option><option value="white">White</option></select></label></div><div className="caption-actions"><button className="button secondary small" onClick={() => void reflowCaptionTrack(activeTrack.id, activeTrack.grouping.max_words_per_line, activeTrack.grouping.max_lines).then(onTrack).catch((error) => setMessage(error.message))}>Reflow phrases</button><span>Drag caption text in the preview to reposition it.</span></div><div className="caption-word-list">{activeTrack.segments.map((segment) => <div key={segment.id}><small>{segment.start_seconds.toFixed(2)}–{segment.end_seconds.toFixed(2)}</small>{segment.words.map((word) => <input key={word.id} aria-label={`Caption word ${word.ordinal}`} value={word.text} onChange={(e) => void updateCaptionWord(word.id, e.target.value).then(onTrack).catch((error) => setMessage(error.message))}/>)}</div>)}</div></div>}
      {message && <p className="caption-error" role="alert">{message}</p>}
    </>}
  </section>
}
