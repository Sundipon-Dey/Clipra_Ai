import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Download, ExternalLink, FileText, LoaderCircle, RefreshCw, Sparkles, Video } from 'lucide-react'
import { downloadClipwingEntry, getClipwingImport, getClipwingImports, refreshClipwingDetails, startClipwingImport, type ClipwingEntry, type ClipwingImport } from './api'

type Props = { projectId: string; onOpenClip: (entry: ClipwingEntry) => void; onProjectChanged: () => void }
const lookupActive = (job: ClipwingImport) => ['queued', 'downloading'].includes(job.status)
const active = (job: ClipwingImport) => lookupActive(job) || job.entries.some((entry) => entry.status === 'cutting')
function stamp(value: number) { const min = Math.floor(value / 60); return `${min}:${(value - min * 60).toFixed(0).padStart(2, '0')}` }
function prettyBytes(value: number | null) {
  if (!value || value <= 0) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let amount = value, unit = 0
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1 }
  return ` · ~${amount.toFixed(amount >= 100 ? 0 : 1)} ${units[unit]}`
}

export default function ClipwingImportPanel({ projectId, onOpenClip, onProjectChanged }: Props) {
  const [text, setText] = useState('')
  const [confirmRights, setConfirmRights] = useState(false)
  const [jobs, setJobs] = useState<ClipwingImport[]>([])
  const [formatsByEntry, setFormatsByEntry] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const refreshedEntries = useRef(new Set<string>())
  const refresh = useCallback(async () => setJobs(await getClipwingImports(projectId)), [projectId])

  useEffect(() => { void refresh().catch((cause) => setError(cause instanceof Error ? cause.message : 'Clipwing imports could not be loaded.')) }, [refresh])
  useEffect(() => {
    const pending = jobs.filter(active)
    if (!pending.length) return
    const timer = window.setInterval(() => {
      void Promise.all(pending.map((job) => getClipwingImport(projectId, job.id).catch(() => null))).then((updates) => {
        const readyEntries = updates.flatMap((job) => job?.entries.filter((entry) => entry.status === 'ready') ?? [])
        if (readyEntries.some((entry) => !refreshedEntries.current.has(entry.id))) {
          readyEntries.forEach((entry) => refreshedEntries.current.add(entry.id))
          onProjectChanged()
        }
        setJobs((current) => current.map((job) => updates.find((item) => item?.id === job.id) ?? job))
      })
    }, 1000)
    return () => window.clearInterval(timer)
  }, [jobs, projectId, onProjectChanged])

  async function submit(event: FormEvent) {
    event.preventDefault(); setError(''); setBusy(true)
    try {
      const job = await startClipwingImport(projectId, text, confirmRights)
      setJobs((current) => [job, ...current.filter((value) => value.id !== job.id)])
      setText(''); setConfirmRights(false)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Clipwing analysis could not be submitted.') }
    finally { setBusy(false) }
  }

  async function downloadEntry(job: ClipwingImport, entry: ClipwingEntry, formatId: string) {
    setError('')
    try {
      const updated = await downloadClipwingEntry(projectId, job.id, entry.id, formatId)
      setJobs((current) => current.map((item) => item.id === job.id ? updated : item))
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'This clip download could not start.') }
  }

  async function refreshDetails(job: ClipwingImport) {
    setError('')
    try {
      const updated = await refreshClipwingDetails(projectId, job.id)
      setJobs((current) => current.map((item) => item.id === job.id ? updated : item))
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Video details could not be refreshed.') }
  }

  return <section className="clipwing-import-panel" aria-labelledby="clipwing-import-title">
    <header><span className="clipwing-icon"><Sparkles size={17}/></span><div><p className="eyebrow">EXTERNAL ANALYSIS IMPORT</p><h2 id="clipwing-import-title">Paste Clipwing analysis</h2><p>Paste the complete results. CLIPRA reads the titles, timestamps, scores, excerpts, and YouTube links.</p></div></header>
    <form onSubmit={(event) => void submit(event)}>
      <label className="editor-field" htmlFor="clipwing-analysis">Clipwing results<textarea id="clipwing-analysis" value={text} onChange={(event) => setText(event.target.value)} placeholder={'1. Highlight title (0:53-2:06, score 95)\n"The transcript excerpt goes here."\nhttps://youtu.be/VIDEO_ID?t=53'} rows={8}/></label>
      <p className="clipwing-quality-note">First, CLIPRA checks available formats and resolutions. Nothing downloads until you choose a format and click Download for an individual clip. Only the selected time range is fetched and recompressed as an H.264/AAC MP4. Run Whisper locally from each clip’s editor when you want captions.</p>
      <label className="clipwing-consent"><input type="checkbox" checked={confirmRights} onChange={(event) => setConfirmRights(event.target.checked)}/><span>I have permission to download and edit this public video. CLIPRA will fetch it from YouTube without account cookies.</span></label>
      {error && <p className="clipwing-error" role="alert">{error}</p>}
      <button className="button primary" disabled={busy || !text.trim() || !confirmRights}>{busy ? <><LoaderCircle size={15} className="spin"/> Checking video details...</> : <><FileText size={15}/> Check video details</>}</button>
    </form>
    {jobs.length > 0 && <div className="clipwing-job-list"><h3>Video details and suggested clips</h3>{jobs.map((job) => <article className="clipwing-job" key={job.id}>
      <div className="clipwing-job-heading"><strong>{lookupActive(job) ? job.stage : job.status === 'failed' || job.status === 'interrupted' ? job.stage : job.video_title ?? 'Video details loaded'}</strong><div>{lookupActive(job) && <span><LoaderCircle size={13} className="spin"/> Looking up once...</span>}{(job.status === 'failed' || job.status === 'interrupted' || !job.formats.length || job.entries.some((entry) => entry.error_message?.toLowerCase().includes('refresh video details'))) && <button className="button secondary small" disabled={lookupActive(job)} onClick={() => void refreshDetails(job)}><RefreshCw size={12}/> Refresh details</button>}</div></div>
      {job.video_duration_seconds !== null && <p className="clipwing-video-meta">Video duration {stamp(job.video_duration_seconds)} · {job.formats.length} available formats (up to 2160p)</p>}
      {job.error_message && <p className="clipwing-error">{job.error_message}</p>}
      <div className="clipwing-entry-list">{job.entries.map((entry) => {
        const requestedFormat = entry.selected_format_id ?? formatsByEntry[entry.id]
        const formatId = job.formats.some((format) => format.format_id === requestedFormat) ? requestedFormat! : job.formats[0]?.format_id ?? ''
        const selectedFormat = job.formats.find((format) => format.format_id === formatId)
        const invalidRange = job.video_duration_seconds !== null && entry.end_seconds > job.video_duration_seconds + .1
        const canDownload = job.status === 'completed' && Boolean(formatId) && !invalidRange && entry.status !== 'cutting' && entry.status !== 'ready'
        const statusLabel = entry.status === 'cutting' ? 'Downloading and recompressing' : entry.status === 'ready' ? 'Downloaded' : entry.status === 'failed' ? 'Download failed' : entry.status === 'interrupted' ? 'Interrupted — retry available' : lookupActive(job) ? 'Waiting for video details' : invalidRange ? 'Timestamp exceeds video duration' : 'Ready to download'
        return <div className="clipwing-entry" key={entry.id}>
          <div className="clipwing-entry-main"><span className={`clipwing-entry-state ${entry.status}`}>{entry.status === 'ready' ? <Video size={13}/> : entry.status === 'cutting' || lookupActive(job) ? <LoaderCircle size={13} className="spin"/> : <FileText size={13}/>}</span><div><strong>{entry.title}</strong><small>{stamp(entry.start_seconds)}–{stamp(entry.end_seconds)}{entry.score !== null ? ` · Score ${Math.round(entry.score)}` : ''} · {statusLabel}</small>{entry.transcript && <p className="clipwing-transcript">“{entry.transcript}”</p>}{entry.error_message && <p className="clipwing-error">{entry.error_message}</p>}
            {job.formats.length > 0 && <label className="clipwing-format-field">Format and resolution<select aria-label={`Format and resolution for ${entry.title}`} value={formatId} disabled={entry.status === 'cutting' || entry.status === 'ready'} onChange={(event) => setFormatsByEntry((current) => ({ ...current, [entry.id]: event.target.value }))}>{job.formats.map((format) => <option key={format.format_id} value={format.format_id}>{format.label}{prettyBytes(format.filesize_bytes)}</option>)}</select>{selectedFormat && <small>Selected source: {selectedFormat.width ?? '?'} × {selectedFormat.height} · output: MP4 H.264/AAC</small>}</label>}
            <div className="clipwing-entry-progress"><div><span>{entry.status === 'cutting' ? 'Clip download progress' : entry.status === 'ready' ? 'Download complete' : 'Clip download progress'}</span><span>{Math.round(entry.progress * 100)}%</span></div><progress max={1} value={entry.progress}/></div>
          </div>
          <div className="clipwing-entry-actions">{entry.status === 'ready' && entry.media_id && entry.clip_id ? <button className="button secondary small" onClick={() => onOpenClip(entry)}>Edit clip <ExternalLink size={13}/></button> : <button className="button secondary small" disabled={!canDownload} onClick={() => void downloadEntry(job, entry, formatId)}><Download size={13}/>{entry.status === 'failed' || entry.status === 'interrupted' ? 'Retry download' : 'Download clip'}</button>}</div>
        </div>
        </div>
      })}</div>
    </article>)}</div>}
  </section>
}
