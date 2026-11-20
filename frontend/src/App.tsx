import { useCallback, useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react'
import {
  ArrowLeft, ArrowUpFromLine, Check, ChevronRight, Clapperboard, Clock3, Film,
  FolderOpen, HardDrive, LoaderCircle, Plus, RefreshCw, ShieldCheck, Video,
  X, XCircle, Sparkles, Trash2,
} from 'lucide-react'
import {
  createProject, deleteProject, deleteClip, getAnalysis, getAnalysisHistory, getProject, getProjects, startAnalysis, uploadVideo,
  type AnalysisRun, type Health, type MediaAsset, type Project, type ProjectDetail,
} from './api'
import MediaPlayer from './MediaPlayer'
import AnalysisReview from './AnalysisReview'
import AnalysisConsentModal from './AnalysisConsentModal'
import ClipEditor from './ClipEditor'
import { createCandidateClip, createManualClip, getClips, type DraftClip, type HighlightCandidate } from './api'

type UploadItem = {
  id: string
  file: File
  state: 'queued' | 'uploading' | 'imported' | 'failed'
  progress: number
  error?: string
}

const allowedFormats = '.mp4,.mov,.mkv,.avi,.webm'

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let amount = bytes / 1024
  let unit = 0
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1 }
  return `${amount.toFixed(amount >= 100 ? 0 : 1)} ${units[unit]}`
}

function formatDuration(value: number) {
  const minutes = Math.floor(value / 60)
  const seconds = value - minutes * 60
  return minutes > 0 ? `${minutes}:${seconds.toFixed(1).padStart(4, '0')}` : `${seconds.toFixed(1)} sec`
}

function formatFrameRate(value: number | null, raw: string | null) {
  return value ? `${value.toFixed(value % 1 === 0 ? 0 : 2)} fps` : raw ? `${raw} fps` : '—'
}

function formatContainer(media: MediaAsset) {
  const extension = fileExtension(media.original_filename).toLowerCase()
  const formats = media.container_format.split(',')
  if (extension === 'mp4' && formats.includes('mp4')) return 'MP4'
  if (extension === 'mov' && formats.includes('mov')) return 'QuickTime MOV'
  if (extension === 'mkv' && formats.includes('matroska')) return 'Matroska'
  if (extension === 'avi' && formats.includes('avi')) return 'AVI'
  if (extension === 'webm' && formats.includes('webm')) return 'WebM'
  return formats[0] || media.container_format
}

export default function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [activeProject, setActiveProject] = useState<ProjectDetail | null>(null)
  const [connection, setConnection] = useState<'checking' | 'connected' | 'offline'>('checking')
  const [uploadLimit, setUploadLimit] = useState(20 * 1024 ** 3)
  const [pageError, setPageError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [projectName, setProjectName] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [selectedFiles, setSelectedFiles] = useState<UploadItem[]>([])
  const [uploading, setUploading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [activeMedia, setActiveMedia] = useState<MediaAsset | null>(null)
  const [analysisHistory, setAnalysisHistory] = useState<Record<string, AnalysisRun[]>>({})
  const [clipsByMedia, setClipsByMedia] = useState<Record<string, DraftClip[]>>({})
  const [editingClip, setEditingClip] = useState<{ media: MediaAsset; clip: DraftClip } | null>(null)
  const [pendingAnalysisMedia, setPendingAnalysisMedia] = useState<MediaAsset | null>(null)
  const [analysisStarting, setAnalysisStarting] = useState(false)
  const [geminiConfigured, setGeminiConfigured] = useState(false)
  const [geminiModel, setGeminiModel] = useState('gemini-3.5-flash-lite')
  const [geminiFileLimit, setGeminiFileLimit] = useState(2 * 1024 ** 3)
  const [activePreviewRange, setActivePreviewRange] = useState<{ startSeconds: number; endSeconds: number } | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const refreshProjects = useCallback(async () => {
    const result = await getProjects()
    setProjects(result)
    return result
  }, [])

  const refreshProject = useCallback(async (projectId: string) => {
    const result = await getProject(projectId)
    setActiveProject(result)
    setProjects((current) => current.map((project) => project.id === result.id
      ? { ...project, name: result.name, media_count: result.media_count, updated_at: result.updated_at }
      : project))
    return result
  }, [])

  useEffect(() => {
    let mounted = true
    async function load() {
      try {
        const apiBase = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')
        const health = await fetch(`${apiBase}/api/health`, { cache: 'no-store' })
        if (!health.ok) throw new Error('The local API returned an error.')
        const healthData = await health.json() as Health
        if (healthData.status !== 'ok' || healthData.service !== 'clipra-api') throw new Error('The local API health response was invalid.')
        if (!mounted) return
        setUploadLimit(Number(healthData.max_upload_bytes) || uploadLimit)
        setGeminiConfigured(healthData.gemini_configured === 'true')
        setGeminiModel(healthData.gemini_model)
        setGeminiFileLimit(Number(healthData.gemini_file_max_bytes) || geminiFileLimit)
        setConnection('connected')
        setPageError(null)
        const result = await getProjects()
        if (mounted) setProjects(result)
      } catch (error) {
        if (!mounted) return
        setConnection('offline')
        setPageError(error instanceof Error ? error.message : 'The local API is unavailable.')
      }
    }
    void load()
    return () => { mounted = false }
  }, [])

  useEffect(() => {
    if (!activeProject) return
    let cancelled = false
    for (const media of activeProject.media) {
      void getAnalysisHistory(media.id).then((runs) => {
        if (!cancelled) setAnalysisHistory((current) => ({ ...current, [media.id]: runs }))
      }).catch(() => undefined)
      void getClips(media.id).then((clips) => {
        if (!cancelled) setClipsByMedia((current) => ({ ...current, [media.id]: clips }))
      }).catch(() => undefined)
    }
    return () => { cancelled = true }
  }, [activeProject?.id, activeProject?.media.map((media) => media.id).join(',')])

  useEffect(() => {
    const activeRuns = Object.values(analysisHistory).flat().filter((run) => ['queued', 'uploading', 'processing_file', 'analyzing'].includes(run.status))
    if (!activeRuns.length) return
    let cancelled = false
    const timer = window.setTimeout(async () => {
      const results = await Promise.all(activeRuns.map((run) => getAnalysis(run.id).catch(() => null)))
      if (cancelled) return
      setAnalysisHistory((current) => {
        const next = { ...current }
        for (const result of results) {
          if (!result) continue
          next[result.media_id] = (next[result.media_id] ?? []).map((run) => run.id === result.id ? result : run)
        }
        return next
      })
    }, 1800)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [analysisHistory])

  async function openProject(project: Project) {
    setPageError(null)
    try {
      await refreshProject(project.id)
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Could not open this project.')
    }
  }

  async function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setCreating(true)
    setCreateError(null)
    try {
      const created = await createProject(projectName.trim())
      await refreshProjects()
      await refreshProject(created.id)
      setProjectName('')
      setShowCreate(false)
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : 'Project could not be created.')
    } finally {
      setCreating(false)
    }
  }

  function enqueueFiles(files: FileList | File[]) {
    const next = Array.from(files).map((file) => ({
      id: crypto.randomUUID(), file, state: 'queued' as const, progress: 0,
    }))
    if (next.length) setSelectedFiles((current) => [...current, ...next])
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    enqueueFiles(event.dataTransfer.files)
  }

  function updateUpload(id: string, update: Partial<UploadItem>) {
    setSelectedFiles((current) => current.map((item) => item.id === id ? { ...item, ...update } : item))
  }

  async function startImport() {
    if (!activeProject || !selectedFiles.length || uploading) return
    setUploading(true)
    const queue = selectedFiles.filter((item) => item.state === 'queued' || item.state === 'failed')
    for (let offset = 0; offset < queue.length; offset += 2) {
      const group = queue.slice(offset, offset + 2)
      await Promise.all(group.map(async (item) => {
        updateUpload(item.id, { state: 'uploading', progress: 0, error: undefined })
        try {
          await uploadVideo(activeProject.id, item.file, (progress) => updateUpload(item.id, { progress }))
          updateUpload(item.id, { state: 'imported', progress: 100 })
        } catch (error) {
          updateUpload(item.id, {
            state: 'failed',
            error: error instanceof Error ? error.message : 'This file could not be imported.',
          })
        }
      }))
    }
    try {
      await refreshProject(activeProject.id)
      await refreshProjects()
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Imported media could not be reloaded.')
    }
    setUploading(false)
  }

  function updateActiveMedia(updated: MediaAsset) {
    setActiveMedia(updated)
    setActiveProject((project) => project ? {
      ...project,
      media: project.media.map((item) => item.id === updated.id ? updated : item),
    } : project)
  }

  function updateProjectMedia(updated: MediaAsset) {
    setActiveProject((project) => project ? { ...project, media: project.media.map((item) => item.id === updated.id ? updated : item) } : project)
  }

  async function retryConnection() {
    setConnection('checking')
    setPageError(null)
    try {
      const apiBase = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')
      const response = await fetch(`${apiBase}/api/health`, { cache: 'no-store' })
      if (!response.ok) throw new Error('The local API returned an error.')
      const health = await response.json() as Health
      if (health.status !== 'ok' || health.service !== 'clipra-api') throw new Error('The local API health response was invalid.')
      setUploadLimit(Number(health.max_upload_bytes) || uploadLimit)
      setGeminiConfigured(health.gemini_configured === 'true')
      setGeminiModel(health.gemini_model)
      setGeminiFileLimit(Number(health.gemini_file_max_bytes) || geminiFileLimit)
      setConnection('connected')
      await refreshProjects()
    } catch (error) {
      setConnection('offline')
      setPageError(error instanceof Error ? error.message : 'The local API is unavailable.')
    }
  }

  const totalMedia = projects.reduce((total, project) => total + project.media_count, 0)

  function rememberAnalysis(run: AnalysisRun) {
    setAnalysisHistory((current) => {
      const prior = current[run.media_id] ?? []
      return { ...current, [run.media_id]: [run, ...prior.filter((item) => item.id !== run.id)] }
    })
  }

  async function confirmAnalysis() {
    if (!pendingAnalysisMedia || analysisStarting) return
    const media = pendingAnalysisMedia
    const force = true
    setAnalysisStarting(true)
    try {
      rememberAnalysis(await startAnalysis(media.id, force))
      setPendingAnalysisMedia(null)
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Gemini analysis could not be started.')
    } finally {
      setAnalysisStarting(false)
    }
  }

  function previewCandidate(media: MediaAsset, startSeconds: number, endSeconds: number) {
    setActivePreviewRange({ startSeconds, endSeconds })
    setActiveMedia(media)
  }

  async function addCandidateClip(media: MediaAsset, candidate: HighlightCandidate) {
    try {
      const clip = await createCandidateClip(candidate.id)
      setClipsByMedia((current) => ({ ...current, [media.id]: [clip, ...(current[media.id] ?? []).filter((item) => item.id !== clip.id)] }))
      setEditingClip({ media, clip })
    } catch (error) { setPageError(error instanceof Error ? error.message : 'Could not create a draft clip.') }
  }

  async function addManualClip(media: MediaAsset) {
    try {
      const clip = await createManualClip(media.id, 'Untitled clip', 0, Math.min(media.duration_seconds, 15))
      setClipsByMedia((current) => ({ ...current, [media.id]: [clip, ...(current[media.id] ?? [])] }))
      setEditingClip({ media, clip })
    } catch (error) { setPageError(error instanceof Error ? error.message : 'Could not create a draft clip.') }
  }

  return editingClip ? (
    <ClipEditor key={editingClip.clip.id} media={editingClip.media} clip={editingClip.clip} geminiConfigured={geminiConfigured} model={geminiModel} onClose={() => setEditingClip(null)} onMediaUpdated={updateProjectMedia} onSaved={(updated) => { setEditingClip((current) => current ? { ...current, clip: updated } : current); setClipsByMedia((current) => ({ ...current, [updated.media_id]: (current[updated.media_id] ?? []).map((item) => item.id === updated.id ? updated : item) })) }} />
  ) : (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#home" onClick={(event) => { event.preventDefault(); setActiveProject(null) }}>
          <span className="brand-mark"><Clapperboard size={19} strokeWidth={2.2} /></span>
          <span>CLIPRA<span className="brand-dot">.</span>AI</span>
        </a>
        <div className="topbar-right">
          {activeProject && <div className="crumb"><ChevronRight size={14} /><span>{activeProject.name}</span></div>}
          <div className={`connection-indicator ${connection}`}><i />{connection === 'connected' ? 'Local API ready' : connection === 'offline' ? 'API offline' : 'Connecting'}</div>
          <div className="local-badge"><ShieldCheck size={15} /> Private workspace</div>
        </div>
      </header>

      {pageError && (
        <div className="page-alert" role="alert"><XCircle size={17} /><span>{pageError}</span>
          {connection === 'offline' && <button onClick={() => void retryConnection()}>Retry connection</button>}
        </div>
      )}

      {activeProject ? (
        <section className="project-page">
          <button className="back-link" onClick={() => { setActiveProject(null); setSelectedFiles([]) }}><ArrowLeft size={16} /> All projects</button>
          <div className="page-heading project-heading">
            <div><p className="eyebrow">PROJECT MEDIA</p><h1>{activeProject.name}</h1><p className="heading-note">Your source videos stay unchanged. CLIPRA stores a separate managed copy for preview.</p></div>
            <div className="heading-stat"><Film size={17} /><span>{activeProject.media_count} {activeProject.media_count === 1 ? 'video' : 'videos'}</span></div>
          </div>

          <section className={`dropzone ${dragging ? 'dragging' : ''}`} onDragEnter={(event) => { event.preventDefault(); setDragging(true) }} onDragOver={(event) => event.preventDefault()} onDragLeave={(event) => { if (event.currentTarget === event.target) setDragging(false) }} onDrop={handleDrop}>
            <input ref={fileInput} type="file" accept={allowedFormats} multiple hidden onChange={(event) => { if (event.target.files) enqueueFiles(event.target.files); event.target.value = '' }} />
            <div className="drop-icon"><ArrowUpFromLine size={21} /></div>
            <div className="drop-copy"><h2>Bring in your footage</h2><p>Drop videos here or <button className="inline-link" onClick={() => fileInput.current?.click()}>browse files</button></p><small>MP4 · MOV · MKV · AVI · WebM · {formatSize(uploadLimit)} max per file</small></div>
            <button className="button secondary choose-button" onClick={() => fileInput.current?.click()}><Plus size={16} /> Choose videos</button>
          </section>

          {selectedFiles.length > 0 && (
            <section className="upload-panel">
              <div className="upload-panel-header"><div><h2>Import queue</h2><span>{selectedFiles.length} {selectedFiles.length === 1 ? 'file' : 'files'} selected</span></div>
                {!uploading && <button className="icon-button subtle" onClick={() => setSelectedFiles([])} aria-label="Clear import queue"><X size={16} /></button>}
              </div>
              <div className="upload-list">
                {selectedFiles.map((item) => <div className="upload-item" key={item.id}>
                  <span className={`upload-state ${item.state}`}>{item.state === 'imported' ? <Check size={14} /> : item.state === 'failed' ? <XCircle size={14} /> : item.state === 'uploading' ? <LoaderCircle size={14} className="spin" /> : <Video size={14} />}</span>
                  <div className="upload-file"><strong>{item.file.name}</strong><span>{formatSize(item.file.size)}{item.state === 'uploading' ? ` · ${item.progress}% sent` : ''}</span>{item.state === 'uploading' && <div className="progress-track"><i style={{ width: `${item.progress}%` }} /></div>}{item.error && <small className="upload-error">{item.error}</small>}</div>
                  {!uploading && item.state === 'queued' && <button className="icon-button subtle" onClick={() => setSelectedFiles((current) => current.filter((queued) => queued.id !== item.id))} aria-label={`Remove ${item.file.name} from queue`}><X size={15} /></button>}
                </div>)}
              </div>
              <div className="upload-actions"><p>Files are checked independently with FFprobe.</p><button className="button primary" disabled={uploading || !selectedFiles.some((item) => item.state === 'queued' || item.state === 'failed')} onClick={() => void startImport()}>{uploading ? <><LoaderCircle size={16} className="spin" /> Importing…</> : <><ArrowUpFromLine size={16} /> Import {selectedFiles.filter((item) => item.state === 'queued' || item.state === 'failed').length} {selectedFiles.filter((item) => item.state === 'queued' || item.state === 'failed').length === 1 ? 'video' : 'videos'}</>}</button></div>
            </section>
          )}

          <section className="library-section">
            <div className="section-heading"><div><p className="eyebrow">MEDIA LIBRARY</p><h2>Imported videos</h2></div>{activeProject.media.length > 0 && <span className="result-count">{activeProject.media.length} items</span>}</div>
            {activeProject.media.length > 0 && <aside className="gemini-notice"><span className="notice-icon"><Sparkles size={16} /></span><div><strong>Gemini video analysis</strong><p>Analysis uploads a temporary managed copy of the selected video to Google. Usage is subject to your Gemini API quota and may incur charges depending on your Google AI Studio plan. Google Files API uploads expire automatically after 48 hours.</p><small>{geminiConfigured ? `Configured model: ${geminiModel} · maximum file size ${formatSize(geminiFileLimit)}` : 'Add GEMINI_API_KEY to backend/.env to enable analysis.'}</small></div></aside>}
            {activeProject.media.length === 0 ? (
              <div className="empty-library"><span className="empty-icon"><FolderOpen size={22} /></span><h3>No videos in this project yet</h3><p>Import authorized footage to see FFprobe metadata and preview your source clips here.</p><button className="button secondary" onClick={() => fileInput.current?.click()}><Plus size={15} /> Select video files</button></div>
            ) : (
              <div className="media-list">
                {activeProject.media.map((media) => <article className="media-row" key={media.id}>
                  <button className="media-preview-thumb" onClick={() => setActiveMedia(media)} aria-label={`Preview ${media.original_filename}`}><span><Video size={20} /></span><i>Preview</i></button>
                  <div className="media-main"><div className="media-name-line"><h3 title={media.original_filename}>{media.original_filename}</h3><span className="format-pill">{fileExtension(media.original_filename)}</span></div>
                    <div className="media-meta"><span><Clock3 size={13} />{formatDuration(media.duration_seconds)}</span><span><Film size={13} />{media.width} × {media.height}</span><span><RefreshCw size={12} />{formatFrameRate(media.frame_rate_decimal, media.frame_rate)}</span><span><HardDrive size={13} />{formatSize(media.size_bytes)}</span></div>
                    <div className="codec-line"><span>Video <b>{media.video_codec}</b></span><span>Audio <b>{media.audio_codec ?? 'No audio'}</b></span><span title={media.container_format}>Container <b>{formatContainer(media)}</b></span></div>
                  </div>
                  <div className="media-trailing"><div className={`proxy-state ${media.preview_status}`}><i />{media.preview_status === 'ready' ? 'Preview copy ready' : media.preview_status === 'processing' ? 'Preparing preview' : media.preview_status === 'failed' ? 'Preview failed' : 'Source ready'}</div><button className="button secondary small" onClick={() => { setActivePreviewRange(null); setActiveMedia(media) }}>Open preview</button><button className="button secondary small" onClick={() => void addManualClip(media)}>New clip</button></div>
                  <div className="draft-clip-list"><div className="draft-list-heading"><strong>Draft clips</strong><span>{(clipsByMedia[media.id] ?? []).length}</span></div>{(clipsByMedia[media.id] ?? []).map((clip) => <div className="draft-clip-row" key={clip.id}><button className="draft-open" onClick={() => setEditingClip({ media, clip })}><span><strong>{clip.title}</strong><small>{formatDuration(clip.start_seconds)}–{formatDuration(clip.end_seconds)} · {clip.framing_mode.replaceAll('_', ' ')}</small></span><span className={`mini-job ${clip.framing_status}`}>{clip.framing_status === 'pending' ? 'Suggesting focal point' : clip.framing_status === 'completed' ? 'Smart Crop ready' : 'Draft'}</span></button><button className="button secondary small" aria-label={`Delete draft ${clip.title}`} onClick={async () => { if (!window.confirm(`Delete draft “${clip.title}” and its captions?`)) return; try { await deleteClip(clip.id); setClipsByMedia((current) => ({ ...current, [media.id]: (current[media.id] ?? []).filter((item) => item.id !== clip.id) })) } catch (error) { window.alert(error instanceof Error ? error.message : 'Could not delete draft.') } }}>Delete</button></div>)}</div>
                  <AnalysisReview media={media} runs={analysisHistory[media.id] ?? []} geminiConfigured={geminiConfigured} onAnalyze={() => setPendingAnalysisMedia(media)} onPreview={(start, end) => previewCandidate(media, start, end)} onCreateClip={(candidate) => void addCandidateClip(media, candidate)} />
                </article>)}
              </div>
            )}
          </section>
        </section>
      ) : (
        <section className="dashboard-page">
          <div className="page-heading dashboard-heading"><div><p className="eyebrow">YOUR WORKSPACE</p><h1>Projects</h1><p className="heading-note">Import local video, inspect its real media details, and preview it safely.</p></div>
            <button className="button primary" onClick={() => { setShowCreate(true); setCreateError(null) }} disabled={connection !== 'connected'}><Plus size={17} /> New project</button>
          </div>

          <div className="stats-row"><div className="stat-card"><span className="stat-icon"><FolderOpen size={17} /></span><div><strong>{projects.length}</strong><small>Projects</small></div></div><div className="stat-card"><span className="stat-icon"><Film size={17} /></span><div><strong>{totalMedia}</strong><small>Imported videos</small></div></div><div className="stat-card"><span className="stat-icon"><HardDrive size={17} /></span><div><strong>On device</strong><small>Source copies stay local</small></div></div></div>

          <div className="section-heading project-list-heading"><div><p className="eyebrow">LIBRARY</p><h2>Recent projects</h2></div><span className="result-count">{projects.length} total</span></div>
          {projects.length === 0 ? (
            <div className="empty-projects"><span className="empty-icon"><Clapperboard size={23} /></span><h3>Start with a project</h3><p>Create a project to group the videos you want to inspect. Your original files will never be modified.</p><button className="button primary" onClick={() => { setShowCreate(true); setCreateError(null) }} disabled={connection !== 'connected'}><Plus size={16} /> Create your first project</button>{connection !== 'connected' && <small>Start the backend service to create a project.</small>}</div>
          ) : (
            <div className="project-grid">{projects.map((project) => <div className="project-card" key={project.id}>
              <button className="project-open" aria-label={`Open project ${project.name}`} onClick={() => void openProject(project)}><div className="project-card-top"><span className="project-card-icon"><FolderOpen size={20} /></span><ChevronRight size={17} className="project-arrow" /></div>
              <h3>{project.name}</h3><p>{project.media_count} {project.media_count === 1 ? 'video' : 'videos'}</p>
              <div className="project-card-foot"><span>Local project</span><span>{new Date(project.updated_at).toLocaleDateString()}</span></div></button><button className="project-delete" onClick={async () => { if (!window.confirm(`Delete project “${project.name}” and all its imported app copies?`)) return; try { await deleteProject(project.id); setProjects((current) => current.filter((item) => item.id !== project.id)) } catch (error) { window.alert(error instanceof Error ? error.message : 'Could not delete project.') } }}><Trash2 size={13}/> Delete</button>
            </div>)}</div>
          )}
        </section>
      )}

      <footer className="app-footer"><span>CLIPRA.AI</span><span>Local-first video workspace · Source files stay yours</span></footer>

      {showCreate && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !creating) setShowCreate(false) }}>
        <section className="create-modal" role="dialog" aria-modal="true" aria-labelledby="create-title">
          <header className="modal-heading"><div><span className="project-card-icon"><FolderOpen size={19} /></span><div><h2 id="create-title">Create a project</h2><p>Group local videos in one workspace.</p></div></div><button className="icon-button" onClick={() => setShowCreate(false)} disabled={creating} aria-label="Close"><X size={18} /></button></header>
          <form onSubmit={(event) => void handleCreateProject(event)}><label htmlFor="project-name">Project name</label><input id="project-name" autoFocus maxLength={100} placeholder="For example, Vyrush HQ highlights" value={projectName} onChange={(event) => setProjectName(event.target.value)} required />{createError && <p className="form-error">{createError}</p>}<div className="modal-actions"><button type="button" className="button secondary" onClick={() => setShowCreate(false)} disabled={creating}>Cancel</button><button type="submit" className="button primary" disabled={creating || !projectName.trim()}>{creating ? <><LoaderCircle size={15} className="spin" /> Creating…</> : <><Plus size={15} /> Create project</>}</button></div></form>
        </section>
      </div>}

      {activeMedia && <MediaPlayer key={activeMedia.id + '-' + (activePreviewRange?.startSeconds ?? 'full')} media={activeMedia} previewRange={activePreviewRange} onClose={() => { setActiveMedia(null); setActivePreviewRange(null) }} onMediaUpdated={updateActiveMedia} />}
      {pendingAnalysisMedia && <AnalysisConsentModal media={pendingAnalysisMedia} model={geminiModel} maxBytes={geminiFileLimit} configured={geminiConfigured} busy={analysisStarting} onCancel={() => setPendingAnalysisMedia(null)} onConfirm={() => void confirmAnalysis()} />}
    </main>
  )
}

function fileExtension(filename: string) {
  const extension = filename.includes('.') ? filename.split('.').pop() : ''
  return extension ? extension.toUpperCase() : 'VIDEO'
}
