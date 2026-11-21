import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, ChevronDown, Download, LoaderCircle, Play } from 'lucide-react'
import { getRenderHistory, mediaUrl, requestClipExport, type DraftClip, type RenderJob } from './api'

type Props = { clip: DraftClip; captionTrackId: string | null; sourceWidth: number; sourceHeight: number; onEdit: () => void }
const active = (job: RenderJob) => job.status === 'queued' || job.status === 'processing'

export default function ClipRenderWorkflow({ clip, captionTrackId, sourceWidth, sourceHeight, onEdit }: Props) {
  const [jobs, setJobs] = useState<RenderJob[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [resolution, setResolution] = useState<'1080' | '1440'>('1080')
  const canExport1440 = Math.min(sourceWidth, sourceHeight) >= 1440
  const reload = useCallback(async () => setJobs(await getRenderHistory(clip.id, captionTrackId)), [clip.id, captionTrackId])
  useEffect(() => { void reload().catch((e) => setError(e.message)) }, [reload])
  useEffect(() => {
    if (!jobs.some(active)) return
    const timer = window.setInterval(() => void reload().catch(() => undefined), 1000)
    return () => window.clearInterval(timer)
  }, [jobs, reload])
  const latestExport = jobs.find((job) => job.kind === 'export' && active(job))
  const exportJobs = jobs.filter((job) => job.kind === 'export')
  const exports = exportJobs.filter((job) => job.status === 'completed').sort((a, b) => (b.version_number ?? 0) - (a.version_number ?? 0))
  const latestCompletedExport = exports[0]
  const nextVersion = Math.max(0, ...exportJobs.map((job) => job.version_number ?? 0)) + 1
  const startExport = async () => {
    setBusy(true); setError('')
    try { const job = await requestClipExport(clip.id, captionTrackId, resolution); setJobs((current) => [job, ...current]) }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not start the export.') }
    finally { setBusy(false) }
  }
  return <main className="clip-editor-backdrop clip-editor-page"><section className="clip-editor render-workspace" aria-labelledby="render-title">
    <header className="clip-editor-header"><div><p className="eyebrow">STAGE 5 · EXPORT</p><h2 id="render-title">Export your clip</h2><span>{clip.title} · 9:16 · source video remains unchanged</span></div><button className="button secondary" onClick={onEdit}><ArrowLeft size={15}/> Reopen in Editor</button></header>
    <div className="render-workspace-body">
      <div className="render-review-column">
        {latestCompletedExport?.stream_url ? <video key={latestCompletedExport.id} className="render-review-video" controls playsInline src={mediaUrl(latestCompletedExport.stream_url)} /> : <div className="render-review-empty"><Play size={26}/><p>Your exported video will appear here when rendering is complete.</p></div>}
        <label className="editor-field export-resolution-field">Export resolution<div className="layout-select-wrap"><select aria-label="Export resolution" value={resolution} onChange={(event) => setResolution(event.target.value as '1080' | '1440')}><option value="1080">1080p · 1080 × 1920</option><option value="1440" disabled={!canExport1440}>1440p · 1440 × 2560{canExport1440 ? '' : ' · source below 1440p'}</option></select><ChevronDown size={16} aria-hidden="true"/></div></label>
        <div className="render-actions"><button className="button primary" disabled={busy || Boolean(latestExport)} onClick={() => void startExport()}>Export V{nextVersion}</button></div>
        <p className="render-current-note">Original upload: {sourceWidth} × {sourceHeight}. Exports use H.264 CRF 18. 1440p is enabled only when the original upload is at least 1440p; a vertical crop may be upscaled. Each version keeps its own resolution and is saved separately.</p>
        {latestExport && <JobProgress job={latestExport} label={`Export V${latestExport.version_number ?? ''}`}/>}
        {error && <p role="alert" className="framing-error">{error}</p>}
      </div>
      <aside className="render-history"><h3>Export versions</h3>{exports.length ? exports.map((job) => <article className="render-version" key={job.id}><div><strong>V{job.version_number} · {job.resolution}p</strong><small>{new Date(job.completed_at ?? job.created_at).toLocaleString()}</small></div><div className="render-version-actions"><a className="button secondary small" href={mediaUrl(job.stream_url!)} target="_blank" rel="noreferrer">Play</a><a className="button secondary small" href={mediaUrl(job.download_url!)}><Download size={13}/> Download</a></div></article>) : <p className="render-history-empty">Completed exports will appear here. Each version is kept separately.</p>}{jobs.filter((job) => job.kind === 'export' && job.status === 'failed').map((job) => <p className="framing-error" key={job.id}>V{job.version_number} failed: {job.error_message}</p>)}</aside>
    </div>
  </section></main>
}

function JobProgress({ job, label }: { job: RenderJob; label: string }) {
  return <div className="render-job-progress"><div><strong>{label}</strong><span>{job.status === 'queued' ? 'Queued' : `${Math.round(job.progress * 100)}% · ${job.stage}`}</span></div><progress max={1} value={job.progress}/>{job.error_message && <p className="framing-error">{job.error_message}</p>}<LoaderCircle size={15} className="spin"/></div>
}
