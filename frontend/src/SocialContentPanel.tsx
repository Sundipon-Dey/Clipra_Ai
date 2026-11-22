import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, Clipboard, LoaderCircle, RefreshCw, Save, Sparkles } from 'lucide-react'
import { getSocialContentHistory, saveSocialPackage, startSocialContentGeneration, type SocialContentGeneration, type SocialPackage, type SocialPlatform } from './api'

const platforms: { id: SocialPlatform; label: string }[] = [
  { id: 'tiktok', label: 'TikTok' },
  { id: 'instagram_reels', label: 'Instagram Reels' },
  { id: 'youtube_shorts', label: 'YouTube Shorts' },
  { id: 'facebook_reels', label: 'Facebook Reels' },
]
const fields: Record<SocialPlatform, { key: string; label: string; multiline?: boolean; list?: boolean }[]> = {
  tiktok: [
    { key: 'opening_hook', label: 'Opening hook' }, { key: 'caption', label: 'Caption', multiline: true },
    { key: 'hashtags', label: 'Hashtags', list: true, multiline: true }, { key: 'suggested_keywords', label: 'Suggested keywords', list: true, multiline: true },
    { key: 'alternate_caption', label: 'Alternate caption', multiline: true },
  ],
  instagram_reels: [
    { key: 'opening_hook', label: 'Opening hook' }, { key: 'caption', label: 'Caption', multiline: true },
    { key: 'hashtags', label: 'Hashtags', list: true, multiline: true }, { key: 'suggested_keywords', label: 'Suggested keywords', list: true, multiline: true },
    { key: 'alternate_caption', label: 'Alternate caption', multiline: true },
  ],
  youtube_shorts: [
    { key: 'title', label: 'SEO title' }, { key: 'description', label: 'Description', multiline: true },
    { key: 'hashtags', label: 'Hashtags', list: true, multiline: true }, { key: 'tags', label: 'Tags', list: true, multiline: true },
    { key: 'alternate_title', label: 'Alternate title' },
  ],
  facebook_reels: [
    { key: 'opening_hook', label: 'Opening hook' }, { key: 'caption', label: 'Post caption', multiline: true },
    { key: 'hashtags', label: 'Hashtags', list: true, multiline: true }, { key: 'suggested_keywords', label: 'Suggested keywords', list: true, multiline: true },
    { key: 'alternate_caption', label: 'Alternate caption', multiline: true },
  ],
}
const active = (generation: SocialContentGeneration) => ['queued', 'uploading', 'processing_file', 'generating'].includes(generation.status)
const valueText = (value: string | string[] | undefined) => Array.isArray(value) ? value.join('\n') : (value ?? '')

export default function SocialContentPanel({ renderJobId, version }: { renderJobId: string; version: number }) {
  const [history, setHistory] = useState<SocialContentGeneration[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [platform, setPlatform] = useState<SocialPlatform>('tiktok')
  const [drafts, setDrafts] = useState<Partial<Record<SocialPlatform, SocialPackage>>>({})
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const initializedGeneration = useRef('')

  const reload = useCallback(async () => {
    const next = await getSocialContentHistory(renderJobId)
    setHistory(next)
    setSelectedId((current) => current || next[0]?.id || '')
  }, [renderJobId])
  useEffect(() => { void reload().catch((reason) => setError(reason instanceof Error ? reason.message : 'Could not load social content.')) }, [reload])
  useEffect(() => {
    if (!history.some(active)) return
    const timer = window.setInterval(() => void reload().catch(() => undefined), 1200)
    return () => window.clearInterval(timer)
  }, [history, reload])

  const selected = useMemo(() => history.find((item) => item.id === selectedId) ?? null, [history, selectedId])
  useEffect(() => {
    if (!selected?.packages || initializedGeneration.current === selected.id) return
    setDrafts(Object.fromEntries(platforms.map(({ id }) => [id, selected.packages?.[id] ? structuredClone(selected.packages[id]) : {}])) as Partial<Record<SocialPlatform, SocialPackage>>)
    initializedGeneration.current = selected.id
  }, [selected?.id, selected?.status])

  const startGeneration = async () => {
    setBusy(true); setError(''); setNotice('')
    try {
      const generation = await startSocialContentGeneration(renderJobId)
      setHistory((current) => [generation, ...current])
      setSelectedId(generation.id)
      setPlatform('tiktok')
      setConsent(false)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not start generation.') }
    finally { setBusy(false) }
  }

  const save = async () => {
    if (!selected || !drafts[platform]) return
    setBusy(true); setError(''); setNotice('')
    try {
      const updated = await saveSocialPackage(selected.id, platform, drafts[platform]!)
      setHistory((current) => current.map((item) => item.id === updated.id ? updated : item))
      setNotice(`${platforms.find((item) => item.id === platform)?.label} changes saved.`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save this package.') }
    finally { setBusy(false) }
  }

  const copy = async (value: string, label: string) => {
    try { await navigator.clipboard.writeText(value); setNotice(`${label} copied.`); setError('') }
    catch { setError('Clipboard access was unavailable. Select and copy the text manually.') }
  }

  const currentPackage = drafts[platform] ?? {}
  const savedPackage = selected?.packages?.[platform] ?? {}
  const dirty = JSON.stringify(currentPackage) !== JSON.stringify(savedPackage)
  const hasUnsavedEdits = Boolean(selected?.packages && platforms.some(({ id }) => JSON.stringify(drafts[id] ?? selected.packages?.[id]) !== JSON.stringify(selected.packages?.[id])))
  const packageText = fields[platform].map(({ key, label }) => `${label}:\n${valueText(currentPackage[key])}`).join('\n\n')

  return <section className="social-content-panel" aria-label={`Social content for export V${version}`}>
    <header className="social-content-heading"><div><p className="eyebrow">STAGE 6 · SOCIAL CONTENT</p><h3>Post copy for export V{version}</h3><p>Generated text is separate from subtitles embedded in the MP4. Nothing is published.</p></div><Sparkles size={19} aria-hidden="true"/></header>
    <div className="social-content-disclosure"><strong>Google upload for this generation</strong><p>The completed V{version} MP4 and its title, transcript/caption text, and available Clipwing moment details will be sent to Google Gemini. This may use quota or incur charges. Google’s free-tier terms may use submitted content to improve its products. The configured upload-size and video-duration limits are checked; an oversized export is rejected without recompression. The video is uploaded as a temporary Gemini file; CLIPRA requests deletion after processing.</p></div>
    <label className="social-consent"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /><span>I authorize uploading this completed export and its listed context to Google for this generation only.</span></label>
    <div className="social-content-toolbar"><button className="button primary" disabled={!consent || busy || history.some(active) || hasUnsavedEdits} onClick={() => void startGeneration()}><Sparkles size={14}/>{history.length ? 'Generate new version' : 'Generate social content'}</button>
      {history.length > 0 && <label className="social-generation-select">Generation<select aria-label="Social content generation" disabled={hasUnsavedEdits} value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>{history.map((item, index) => <option key={item.id} value={item.id}>Generation {history.length - index} · {item.status}</option>)}</select></label>}
    </div>
    {hasUnsavedEdits && <p className="social-copy-note">Save or discard your unsaved edits before switching generations or starting another one.</p>}
    {selected && active(selected) && <div className="social-generation-progress"><div><LoaderCircle size={15} className="spin"/><strong>{selected.stage.replaceAll('_', ' ')}</strong><span>{Math.round(selected.progress * 100)}%</span></div><progress max={1} value={selected.progress}/><small>Upload progress is reported by phase; Gemini does not provide byte-level upload progress here.</small></div>}
    {selected?.status === 'failed' && <p className="framing-error">{selected.error_message}{selected.cleanup_pending ? ' Google file cleanup is still pending.' : ''}</p>}
    {selected?.status === 'interrupted' && <p className="framing-error">This request was interrupted and was not retried. Review the export and start a new generation when ready.</p>}
    {selected?.status === 'completed' && selected.packages && <>
      <div className="social-platform-tabs" role="tablist" aria-label="Social platform packages">{platforms.map((item) => <button key={item.id} role="tab" aria-selected={platform === item.id} className={platform === item.id ? 'selected' : ''} onClick={() => { setPlatform(item.id); setNotice('') }}>{item.label}</button>)}</div>
      <div className="social-package-actions"><button className="button secondary small" onClick={() => void copy(packageText, 'Package')}><Clipboard size={13}/> Copy package</button><button className="button secondary small" disabled={!dirty || busy} onClick={() => void save()}><Save size={13}/> Save this platform</button><button className="button secondary small" disabled={!hasUnsavedEdits || busy} onClick={() => { setDrafts(Object.fromEntries(platforms.map(({ id }) => [id, structuredClone(selected.packages?.[id] ?? {})])) as Partial<Record<SocialPlatform, SocialPackage>>); setNotice('Unsaved edits discarded.') }}><RefreshCw size={13}/> Discard unsaved edits</button></div>
      <div className="social-package-fields">{fields[platform].map(({ key, label, list, multiline }) => <label key={key} className="editor-field social-package-field">{label}<div className="social-package-input-row">{multiline ? <textarea rows={key === 'description' || key === 'caption' || key === 'alternate_caption' ? 4 : 2} value={valueText(currentPackage[key])} onChange={(event) => setDrafts((current) => ({ ...current, [platform]: { ...current[platform], [key]: list ? event.target.value.split('\n').map((value) => value.trim()).filter(Boolean) : event.target.value } }))}/> : <input value={valueText(currentPackage[key])} onChange={(event) => setDrafts((current) => ({ ...current, [platform]: { ...current[platform], [key]: event.target.value } }))}/>}<button type="button" className="button secondary small" aria-label={`Copy ${label}`} onClick={() => void copy(valueText(currentPackage[key]), label)}><Clipboard size={13}/></button></div></label>)}</div>
      <p className="social-copy-note">Review every generated claim before posting. Suggested keywords and tags are ideas, not ranking guarantees.</p>
    </>}
    {notice && <p className="social-content-notice" role="status"><Check size={13}/>{notice}</p>}
    {error && <p className="framing-error" role="alert">{error}</p>}
  </section>
}
