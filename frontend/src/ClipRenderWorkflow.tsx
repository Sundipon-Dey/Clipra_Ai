import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowLeft, CheckCircle2, Download, LoaderCircle, Play, RefreshCw } from 'lucide-react'
import { approveRenderExport, getRenderHistory, mediaUrl, requestClipRenderPreview, type DraftClip, type RenderJob } from './api'

type Props = { clip: DraftClip; captionTrackId: string | null; onEdit: () => void }
const active = (job: RenderJob) => job.status === 'queued' || job.status === 'processing'

export default function ClipRenderWorkflow({ clip, captionTrackId, onEdit }: Props) {
  const [jobs, setJobs] = useState<RenderJob[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const reload = useCallback(async () => setJobs(await getRenderHistory(clip.id, captionTrackId)), [clip.id, captionTrackId])
  useEffect(() => { void reload().catch((e) => setError(e.message)) }, [reload])
  useEffect(() => {
    if (!jobs.some(active)) return
    const timer = window.setInterval(() => void reload().catch(() => undefined), 1000)
    return () => window.clearInterval(timer)
  }, [jobs, reload])
  const latestPreview = useMemo(() => jobs.find((job) => job.kind === 'preview' && job.status === 'completed' && job.current), [jobs])
  const latestExport = jobs.find((job) => job.kind === 'export' && active(job))
  const exports = jobs.filter((job) => job.kind === 'export' && job.status === 'completed').sort((a, b) => (b.version_number ?? 0) - (a.version_number ?? 0))
  const renderPreview = async () => {
    setBusy(true); setError('')
    try { const job = await requestClipRenderPreview(clip.id, captionTrackId); setJobs((current) => [job, ...current]); await reload() }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not start preview rendering.') }
    finally { setBusy(false) }
  }
  const approve = async () => {
    if (!latestPreview) return
    setBusy(true); setError('')
    try { const job = await approveRenderExport(latestPreview.id); setJobs((current) => [job, ...current]) }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not approve export.') }
    finally { setBusy(false) }
  }
  return <main className="clip-editor-backdrop clip-editor-page"><section className="clip-editor render-workspace" aria-labelledby="render-title">
    <header className="clip-editor-header"><div><p className="eyebrow">STAGE 5 · REVIEW & EXPORT</p><h2 id="render-title">Preview and export</h2><span>{clip.title} · 9:16 · source video remains unchanged</span></div><button className="button secondary" onClick={onEdit}><ArrowLeft size={15}/> Reopen in Editor</button></header>
    <div className="render-workspace-body">
      <div className="render-review-column">
        {latestPreview?.stream_url ? <video key={latestPreview.id} className="render-review-video" controls playsInline src={mediaUrl(latestPreview.stream_url)} /> : <div className="render-review-empty"><Play size={26}/><p>Generate a rendered preview to review framing, captions, timing, and effects.</p></div>}
        <div className="render-actions"><button className="button primary" disabled={busy || Boolean(latestExport)} onClick={() => void renderPreview()}><RefreshCw size={15}/> Generate fresh preview</button><button className="button secondary" disabled={!latestPreview || busy || Boolean(latestExport)} onClick={() => void approve()}><CheckCircle2 size={15}/> Approve & export</button></div>
        {latestPreview && <p className="render-current-note">This preview matches the saved editing settings. Any change makes it ineligible for export; generate a fresh preview after editing.</p>}
        {latestExport && <JobProgress job={latestExport} label={`Export V${latestExport.version_number ?? ''}`}/>}
        {jobs.filter((job) => job.kind === 'preview' && (job.status === 'queued' || job.status === 'processing')).map((job) => <JobProgress key={job.id} job={job} label="Preview"/>)}
        {error && <p role="alert" className="framing-error">{error}</p>}
      </div>
      <aside className="render-history"><h3>Export versions</h3>{exports.length ? exports.map((job) => <article className="render-version" key={job.id}><div><strong>V{job.version_number}</strong><small>{new Date(job.completed_at ?? job.created_at).toLocaleString()}</small></div><div className="render-version-actions"><a className="button secondary small" href={mediaUrl(job.stream_url!)} target="_blank" rel="noreferrer">Play</a><a className="button secondary small" href={mediaUrl(job.download_url!)}><Download size={13}/> Download</a></div></article>) : <p className="render-history-empty">Completed exports will appear here. Each version is kept separately.</p>}{jobs.filter((job) => job.kind === 'export' && job.status === 'failed').map((job) => <p className="framing-error" key={job.id}>V{job.version_number} failed: {job.error_message}</p>)}</aside>
    </div>
  </section></main>
}

function JobProgress({ job, label }: { job: RenderJob; label: string }) {
  return <div className="render-job-progress"><div><strong>{label}</strong><span>{job.status === 'queued' ? 'Queued' : `${Math.round(job.progress * 100)}% · ${job.stage}`}</span></div><progress max={1} value={job.progress}/>{job.error_message && <p className="framing-error">{job.error_message}</p>}<LoaderCircle size={15} className="spin"/></div>
}
