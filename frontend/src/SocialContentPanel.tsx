import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowLeft, Check, CheckCircle2, Clipboard, ExternalLink, LoaderCircle, RefreshCw, Save, ShieldCheck, Sparkles, Upload, Unplug,
} from 'lucide-react'
import {
  connectFacebook, connectInstagram, connectYouTube, disconnectFacebook, disconnectYouTube, getFacebookStatus, getFacebookUploads, getInstagramStatus, getInstagramUploads, getSocialContentHistory, getSocialContentManualPrompt, getYouTubeStatus, getYouTubeUploads, importManualSocialContent, saveSocialPackage, startFacebookUpload, startInstagramUpload, startSocialContentGeneration, startYouTubeUpload,
  type FacebookStatus, type FacebookUpload, type InstagramStatus, type InstagramUpload, type SocialContentGeneration, type SocialPackage, type SocialPlatform, type YouTubeStatus, type YouTubeUpload,
} from './api'

const platforms: { id: SocialPlatform; label: string; detail: string }[] = [
  { id: 'instagram_reels', label: 'Instagram Reels', detail: 'Reel caption & tags' },
  { id: 'youtube_shorts', label: 'YouTube Shorts', detail: 'Title & description' },
  { id: 'facebook_reels', label: 'Facebook Reels', detail: 'Post copy & tags' },
]

const fields: Record<SocialPlatform, { key: string; label: string; multiline?: boolean; list?: boolean }[]> = {
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

function PlatformIcon({ platform }: { platform: SocialPlatform }) {
  if (platform === 'instagram_reels') return <svg viewBox="0 0 24 24" aria-hidden="true" className="brand-instagram"><rect x="3.5" y="3.5" width="17" height="17" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.7" cy="6.7" r=".9" className="brand-instagram-dot"/></svg>
  if (platform === 'youtube_shorts') return <svg viewBox="0 0 24 24" aria-hidden="true" className="brand-youtube"><rect x="2" y="5" width="20" height="14" rx="4"/><path d="m10 8.7 5.5 3.3-5.5 3.3z"/></svg>
  if (platform === 'facebook_reels') return <svg viewBox="0 0 24 24" aria-hidden="true" className="brand-facebook"><path d="M13.4 21v-7.2h2.5l.4-2.9h-2.9V9.1c0-.9.3-1.5 1.5-1.5h1.5V5a20 20 0 0 0-2.2-.1c-2.3 0-3.9 1.4-3.9 4.1v1.9H7.7v2.9h2.6V21z"/></svg>
  return null
}

type Props = {
  renderJobId: string
  version: number
  clipTitle?: string
  videoUrl?: string
  onBack?: () => void
}

export default function SocialContentPanel({ renderJobId, version, clipTitle = 'Your clip', videoUrl, onBack }: Props) {
  const [history, setHistory] = useState<SocialContentGeneration[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [platform, setPlatform] = useState<SocialPlatform>('instagram_reels')
  const [drafts, setDrafts] = useState<Partial<Record<SocialPlatform, SocialPackage>>>({})
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [manualPrompt, setManualPrompt] = useState('')
  const [manualOutput, setManualOutput] = useState('')
  const [manualOpen, setManualOpen] = useState(false)
  const [manualBusy, setManualBusy] = useState(false)
  const [youtubeStatus, setYoutubeStatus] = useState<YouTubeStatus | null>(null)
  const [youtubeUploads, setYoutubeUploads] = useState<YouTubeUpload[]>([])
  const [youtubePrivacy, setYoutubePrivacy] = useState<YouTubeUpload['privacy_status']>('private')
  const [youtubeConsent, setYoutubeConsent] = useState(false)
  const [youtubeBusy, setYoutubeBusy] = useState(false)
  const [waitingForYoutube, setWaitingForYoutube] = useState(false)
  const [facebookStatus, setFacebookStatus] = useState<FacebookStatus | null>(null)
  const [facebookUploads, setFacebookUploads] = useState<FacebookUpload[]>([])
  const [facebookPageId, setFacebookPageId] = useState('')
  const [facebookConsent, setFacebookConsent] = useState(false)
  const [facebookBusy, setFacebookBusy] = useState(false)
  const [waitingForFacebook, setWaitingForFacebook] = useState(false)
  const [instagramStatus, setInstagramStatus] = useState<InstagramStatus | null>(null)
  const [instagramUploads, setInstagramUploads] = useState<InstagramUpload[]>([])
  const [instagramAccountId, setInstagramAccountId] = useState('')
  const [instagramConsent, setInstagramConsent] = useState(false)
  const [instagramBusy, setInstagramBusy] = useState(false)
  const [waitingForInstagram, setWaitingForInstagram] = useState(false)
  const initializedGeneration = useRef('')

  const reload = useCallback(async () => {
    const next = await getSocialContentHistory(renderJobId)
    setHistory(next)
    setSelectedId((current) => current || next[0]?.id || '')
  }, [renderJobId])

  useEffect(() => { void reload().catch((reason) => setError(reason instanceof Error ? reason.message : 'Could not load social content.')) }, [reload])
  const reloadYouTube = useCallback(async () => {
    const [account, uploads] = await Promise.all([getYouTubeStatus(), getYouTubeUploads(renderJobId)])
    setYoutubeStatus(account)
    setYoutubeUploads(uploads)
    if (account.connected) setWaitingForYoutube(false)
  }, [renderJobId])
  useEffect(() => { void reloadYouTube().catch((reason) => setError(reason instanceof Error ? reason.message : 'Could not load YouTube status.')) }, [reloadYouTube])
  useEffect(() => {
    if (!waitingForYoutube) return
    const timer = window.setInterval(() => { void getYouTubeStatus().then((account) => { setYoutubeStatus(account); if (account.connected) setWaitingForYoutube(false); else if (!account.authorization_pending) { setWaitingForYoutube(false); setError('Google authorization did not complete. Check the browser result and try connecting again.') } }).catch(() => undefined) }, 1500)
    return () => window.clearInterval(timer)
  }, [waitingForYoutube])
  const reloadFacebook = useCallback(async () => {
    const [account, uploads] = await Promise.all([getFacebookStatus(), getFacebookUploads(renderJobId)])
    setFacebookStatus(account)
    setFacebookUploads(uploads)
    setFacebookPageId((current) => account.pages.some((page) => page.id === current) ? current : (account.pages[0]?.id ?? ''))
    if (account.connected) setWaitingForFacebook(false)
    if (account.authorization_error) { setError(account.authorization_error); setWaitingForFacebook(false) }
  }, [renderJobId])
  useEffect(() => { void reloadFacebook().catch((reason) => setError(reason instanceof Error ? reason.message : 'Could not load Facebook status.')) }, [reloadFacebook])
  useEffect(() => {
    if (!waitingForFacebook) return
    const timer = window.setInterval(() => { void getFacebookStatus().then((account) => {
      setFacebookStatus(account)
      setFacebookPageId((current) => account.pages.some((page) => page.id === current) ? current : (account.pages[0]?.id ?? ''))
      if (account.connected) { setWaitingForFacebook(false); setError(''); setNotice('Facebook Page connected.') }
      else if (account.authorization_error) { setWaitingForFacebook(false); setError(account.authorization_error) }
    }).catch(() => undefined) }, 1500)
    return () => window.clearInterval(timer)
  }, [waitingForFacebook])
  const reloadInstagram = useCallback(async () => {
    const [account, uploads] = await Promise.all([getInstagramStatus(), getInstagramUploads(renderJobId)])
    setInstagramStatus(account)
    setInstagramUploads(uploads)
    setInstagramAccountId((current) => account.accounts.some((item) => item.instagram_user_id === current) ? current : (account.accounts[0]?.instagram_user_id ?? ''))
    if (account.connected) setWaitingForInstagram(false)
    if (account.authorization_error) { setError(account.authorization_error); setWaitingForInstagram(false) }
  }, [renderJobId])
  useEffect(() => { void reloadInstagram().catch((reason) => setError(reason instanceof Error ? reason.message : 'Could not load Instagram status.')) }, [reloadInstagram])
  useEffect(() => {
    if (!waitingForInstagram) return
    const timer = window.setInterval(() => { void getInstagramStatus().then((account) => {
      setInstagramStatus(account)
      setInstagramAccountId((current) => account.accounts.some((item) => item.instagram_user_id === current) ? current : (account.accounts[0]?.instagram_user_id ?? ''))
      if (account.connected) { setWaitingForInstagram(false); setError(''); setNotice('Instagram professional account connected.') }
      else if (account.authorization_error) { setWaitingForInstagram(false); setError(account.authorization_error) }
    }).catch(() => undefined) }, 1500)
    return () => window.clearInterval(timer)
  }, [waitingForInstagram])
  useEffect(() => {
    if (!youtubeUploads.some((item) => item.status === 'queued' || item.status === 'uploading')) return
    const timer = window.setInterval(() => { void getYouTubeUploads(renderJobId).then(setYoutubeUploads).catch(() => undefined) }, 1000)
    return () => window.clearInterval(timer)
  }, [youtubeUploads, renderJobId])
  useEffect(() => {
    if (!facebookUploads.some((item) => item.status === 'queued' || item.status === 'uploading')) return
    const timer = window.setInterval(() => { void getFacebookUploads(renderJobId).then(setFacebookUploads).catch(() => undefined) }, 1000)
    return () => window.clearInterval(timer)
  }, [facebookUploads, renderJobId])
  useEffect(() => {
    if (!instagramUploads.some((item) => item.status === 'queued' || item.status === 'uploading')) return
    const timer = window.setInterval(() => { void getInstagramUploads(renderJobId).then(setInstagramUploads).catch(() => undefined) }, 1000)
    return () => window.clearInterval(timer)
  }, [instagramUploads, renderJobId])
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
  useEffect(() => { setFacebookConsent(false) }, [selected?.id, facebookPageId])
  useEffect(() => { setInstagramConsent(false) }, [selected?.id, instagramAccountId])

  const startGeneration = async () => {
    setBusy(true); setError(''); setNotice('')
    try {
      const generation = await startSocialContentGeneration(renderJobId)
      setHistory((current) => [generation, ...current])
      setSelectedId(generation.id)
      setPlatform('instagram_reels')
      setConsent(false)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not start generation.') }
    finally { setBusy(false) }
  }

  const copyManualPrompt = async () => {
    if (!selected) return
    setManualBusy(true); setError(''); setNotice('')
    try {
      const result = await getSocialContentManualPrompt(selected.id)
      setManualPrompt(result.prompt)
      setManualOpen(true)
      try {
        await navigator.clipboard.writeText(result.prompt)
        setNotice('Prompt copied. Attach this exact export video in your AI chat, then paste its JSON response below.')
      } catch {
        setNotice('Prompt is ready below. Select and copy it, then attach this exact export video in your AI chat.')
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not prepare the manual prompt.') }
    finally { setManualBusy(false) }
  }

  const importManualOutput = async () => {
    if (!selected || !manualOutput.trim()) return
    setManualBusy(true); setError(''); setNotice('')
    try {
      const updated = await importManualSocialContent(selected.id, manualOutput)
      setHistory((current) => current.map((item) => item.id === updated.id ? updated : item))
      setSelectedId(updated.id)
      setDrafts(Object.fromEntries(platforms.map(({ id }) => [id, updated.packages?.[id] ? structuredClone(updated.packages[id]) : {}])) as Partial<Record<SocialPlatform, SocialPackage>>)
      initializedGeneration.current = updated.id
      setManualOutput(''); setManualOpen(false); setPlatform('instagram_reels')
      setNotice('AI output imported. Review and save each platform package before publishing.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not import the AI output.') }
    finally { setManualBusy(false) }
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

  const connectYoutube = async () => {
    setYoutubeBusy(true); setError(''); setNotice('')
    try {
      const result = await connectYouTube()
      setWaitingForYoutube(true)
      setNotice(result.message)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not start YouTube authorization.') }
    finally { setYoutubeBusy(false) }
  }

  const disconnectYoutube = async () => {
    if (!window.confirm('Disconnect this Google account from CLIPRA.AI? This revokes the saved YouTube authorization.')) return
    setYoutubeBusy(true); setError(''); setNotice('')
    try { setYoutubeStatus(await disconnectYouTube()); setNotice('YouTube account disconnected.') }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not disconnect YouTube.') }
    finally { setYoutubeBusy(false) }
  }

  const uploadYoutube = async () => {
    if (!selected || !youtubeConsent) return
    setYoutubeBusy(true); setError(''); setNotice('')
    try {
      const upload = await startYouTubeUpload(renderJobId, selected.id, youtubePrivacy)
      setYoutubeUploads((current) => [upload, ...current.filter((item) => item.id !== upload.id)])
      setYoutubeConsent(false)
      setNotice(`Export V${version} upload started.`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not start the YouTube upload.') }
    finally { setYoutubeBusy(false) }
  }

  const connectFacebookAccount = async () => {
    setFacebookBusy(true); setError(''); setNotice('')
    try { const result = await connectFacebook(); setWaitingForFacebook(true); setNotice(result.message) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not start Facebook authorization.') }
    finally { setFacebookBusy(false) }
  }

  const disconnectFacebookAccount = async () => {
    if (!window.confirm('Disconnect Facebook from CLIPRA.AI and clear its locally saved Page tokens?')) return
    setFacebookBusy(true); setError(''); setNotice('')
    try { setFacebookStatus(await disconnectFacebook()); setFacebookUploads([]); setFacebookPageId(''); setNotice('Facebook disconnected from this CLIPRA installation.') }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not disconnect Facebook.') }
    finally { setFacebookBusy(false) }
  }

  const publishFacebook = async () => {
    if (!selected || !facebookConsent || !facebookPageId) return
    setFacebookBusy(true); setError(''); setNotice('')
    try {
      const upload = await startFacebookUpload(renderJobId, selected.id, facebookPageId)
      setFacebookUploads((current) => [upload, ...current.filter((item) => item.id !== upload.id)])
      setFacebookConsent(false)
      setNotice(`Export V${version} upload started for ${facebookStatus?.pages.find((page) => page.id === facebookPageId)?.name ?? 'Facebook Page'}.`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not start the Facebook upload.') }
    finally { setFacebookBusy(false) }
  }

  const connectInstagramAccount = async () => {
    setInstagramBusy(true); setError(''); setNotice('')
    try { const result = await connectInstagram(); setWaitingForInstagram(true); setNotice(result.message) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not start Instagram authorization.') }
    finally { setInstagramBusy(false) }
  }

  const publishInstagram = async () => {
    if (!selected || !instagramConsent || !instagramAccountId) return
    setInstagramBusy(true); setError(''); setNotice('')
    try {
      const upload = await startInstagramUpload(renderJobId, selected.id, instagramAccountId)
      setInstagramUploads((current) => [upload, ...current.filter((item) => item.id !== upload.id)])
      setInstagramConsent(false)
      setNotice(`Export V${version} upload started for @${instagramStatus?.accounts.find((item) => item.instagram_user_id === instagramAccountId)?.instagram_username ?? 'Instagram'}.`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not start the Instagram upload.') }
    finally { setInstagramBusy(false) }
  }

  const currentPackage = drafts[platform] ?? {}
  const savedPackage = selected?.packages?.[platform] ?? {}
  const dirty = JSON.stringify(currentPackage) !== JSON.stringify(savedPackage)
  const hasUnsavedEdits = Boolean(selected?.packages && platforms.some(({ id }) => JSON.stringify(drafts[id] ?? selected.packages?.[id]) !== JSON.stringify(selected.packages?.[id])))
  const packageText = fields[platform].map(({ key, label }) => `${label}:\n${valueText(currentPackage[key])}`).join('\n\n')
  const selectedPlatform = platforms.find((item) => item.id === platform)!
  const youtubeUploadActive = youtubeUploads.some((item) => item.status === 'queued' || item.status === 'uploading')
  const facebookUploadActive = facebookUploads.some((item) => item.status === 'queued' || item.status === 'uploading')
  const instagramUploadActive = instagramUploads.some((item) => item.status === 'queued' || item.status === 'uploading')

  return <div className="social-content-page">
    <div className="social-content-shell">
      <header className="social-page-header">
        {onBack && <button className="button secondary social-back-button" onClick={onBack}><ArrowLeft size={15}/> Back to export</button>}
        <div className="social-page-title"><p className="eyebrow">SOCIAL CONTENT</p><h1>Social content studio</h1><p>{clipTitle} <span>·</span> Export V{version} <span>·</span> Posting always requires your approval</p></div>
        <span className="social-page-version">EXPORT <strong>V{version}</strong></span>
      </header>

      <section className="social-content-panel" aria-label={`Social content for export V${version}`}>
        <header className="social-content-heading"><div><h2>Turn this clip into platform-ready copy</h2><p>Review, edit, and save a separate package for each platform.</p></div><span className="social-heading-icon"><Sparkles size={18} aria-hidden="true"/></span></header>
        <div className="social-content-disclosure"><strong>Google upload for this generation</strong><p>The completed V{version} MP4 and its title, transcript/caption text, and available Clipwing moment details will be sent to Google Gemini. This may use quota or incur charges. Google’s free-tier terms may use submitted content to improve its products. The configured upload-size and video-duration limits are checked; an oversized export is rejected without recompression. The video is uploaded as a temporary Gemini file; CLIPRA requests deletion after processing.</p></div>
        <label className="social-consent"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /><span>I authorize uploading this completed export and its listed context to Google for this generation only.</span></label>
        <div className="social-content-toolbar"><button className="button primary" disabled={!consent || busy || history.some(active) || hasUnsavedEdits} onClick={() => void startGeneration()}><Sparkles size={14}/>{history.length ? 'Generate new version' : 'Generate social content'}</button>
          {history.length > 0 && <label className="social-generation-select">Generation<select aria-label="Social content generation" disabled={hasUnsavedEdits} value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>{history.map((item, index) => <option key={item.id} value={item.id}>Generation {history.length - index} · {item.status}</option>)}</select></label>}
        </div>
        {hasUnsavedEdits && <p className="social-copy-note">Save or discard your unsaved edits before switching generations or starting another one.</p>}
        {selected && active(selected) && <div className="social-generation-progress"><div><LoaderCircle size={15} className="spin"/><strong>{selected.stage.replaceAll('_', ' ')}</strong><span>{Math.round(selected.progress * 100)}%</span></div><progress max={1} value={selected.progress}/><small>Upload progress is reported by phase; Gemini does not provide byte-level upload progress here.</small></div>}
        {selected?.status === 'failed' && <>
          <p className="framing-error">{selected.error_message}</p>
          <section className="social-manual-fallback" aria-label="Manual AI fallback">
            <div className="social-manual-heading"><div><strong>Continue with another AI</strong><p>Copy the export-specific prompt, attach this exact V{version} video in Gemini, ChatGPT, or another video-capable AI, then paste the JSON response here. CLIPRA will validate it and fill all four platform packages.</p></div><div className="social-manual-actions"><button className="button secondary" disabled={manualBusy} onClick={() => void copyManualPrompt()}><Clipboard size={14}/> Copy prompt</button><button className="button secondary" disabled={manualBusy} onClick={() => setManualOpen((open) => !open)}><Clipboard size={14}/>{manualOpen ? 'Hide output fields' : 'Paste output'}</button></div></div>
            <small>The prompt includes this export’s title, transcript/caption text, and available Clipwing details. Copying does not upload anything to Google. Attach the video yourself in the AI chat.</small>
            {manualOpen && <div className="social-manual-fields">
              {manualPrompt && <label>Prompt (copied to clipboard when available)<textarea aria-label="Manual AI prompt" readOnly value={manualPrompt} onFocus={(event) => event.currentTarget.select()} rows={8}/></label>}
              <label>Paste the AI’s JSON response<textarea aria-label="Paste AI output" value={manualOutput} onChange={(event) => setManualOutput(event.target.value)} placeholder="Paste the complete four-platform JSON response here…" rows={9}/></label>
              <div className="social-manual-actions"><button className="button primary" disabled={manualBusy || !manualOutput.trim()} onClick={() => void importManualOutput()}>{manualBusy ? <LoaderCircle size={14} className="spin"/> : <Check size={14}/>} Import all four packages</button></div>
            </div>}
          </section>
        </>}
        {selected?.cleanup_pending && <p className="social-cleanup-warning" role="status">Google file cleanup is still pending for this generation. Importing manual output does not change or resolve that cleanup request.</p>}
        {selected?.status === 'interrupted' && <p className="framing-error">This request was interrupted and was not retried. Review the export and start a new generation when ready.</p>}

        {selected?.status === 'completed' && selected.packages && <section className={`social-output-section platform-${platform}`} aria-label="Generated platform copy">
          <header className="social-output-heading"><div className="social-output-mark"><PlatformIcon platform={platform}/></div><div className="social-output-title"><p className="eyebrow">YOUR CONTENT PACK</p><h2>{selectedPlatform.label}</h2><p>{selectedPlatform.detail}</p></div><span className={`social-save-state ${hasUnsavedEdits ? 'is-dirty' : 'is-saved'}`}>{hasUnsavedEdits ? <><span className="social-state-dot"/> Unsaved edits</> : <><CheckCircle2 size={14}/> Up to date</>}</span></header>
          <div className="social-platform-grid" role="tablist" aria-label="Choose a platform">{platforms.map((item) => <button key={item.id} type="button" role="tab" aria-label={item.label} aria-selected={platform === item.id} className={`social-platform-card ${platform === item.id ? 'selected' : ''} platform-${item.id}`} onClick={() => { setPlatform(item.id); setNotice('') }}><span className="social-platform-card-icon"><PlatformIcon platform={item.id}/></span><span className="social-platform-card-copy"><strong>{item.label}</strong><small>{item.detail}</small></span><span className="social-platform-selected"><Check size={13}/></span></button>)}</div>
          <div className="social-output-toolbar"><div><strong>Package details</strong><span>Everything here is editable before you copy or save.</span></div><div className="social-package-actions"><button className="button secondary small" onClick={() => void copy(packageText, 'Package')}><Clipboard size={13}/> Copy package</button><button className="button primary small" aria-label="Save this platform" disabled={!dirty || busy} onClick={() => void save()}><Save size={13}/> Save changes</button><button className="button secondary small" disabled={!hasUnsavedEdits || busy} onClick={() => { setDrafts(Object.fromEntries(platforms.map(({ id }) => [id, structuredClone(selected.packages?.[id] ?? {})])) as Partial<Record<SocialPlatform, SocialPackage>>); setNotice('Unsaved edits discarded.') }}><RefreshCw size={13}/> Discard edits</button></div></div>
          <div className="social-package-fields">{fields[platform].map(({ key, label, list, multiline }) => <label key={key} className="editor-field social-package-field">{label}<div className="social-package-input-row">{multiline ? <textarea rows={key === 'description' || key === 'caption' || key === 'alternate_caption' ? 4 : 2} value={valueText(currentPackage[key])} onChange={(event) => setDrafts((current) => ({ ...current, [platform]: { ...current[platform], [key]: list ? event.target.value.split('\n').map((value) => value.trim()).filter(Boolean) : event.target.value } }))}/> : <input value={valueText(currentPackage[key])} onChange={(event) => setDrafts((current) => ({ ...current, [platform]: { ...current[platform], [key]: event.target.value } }))}/>}<button type="button" className="button secondary small" aria-label={`Copy ${label}`} onClick={() => void copy(valueText(currentPackage[key]), label)}><Clipboard size={13}/></button></div></label>)}</div>
          {platform === 'youtube_shorts' && <>
            <section className="youtube-short-preview" aria-label="Approximate YouTube Shorts preview">
              <div className="youtube-short-preview-title"><div><PlatformIcon platform="youtube_shorts"/><strong>Shorts preview</strong></div><span>Approximate platform view</span></div>
              <div className="youtube-short-preview-phone"><div className="youtube-short-preview-video">{videoUrl ? <video src={videoUrl} controls playsInline preload="metadata"/> : <div className="youtube-preview-missing">Export preview unavailable</div>}<div className="youtube-short-preview-actions"><span>Like</span><span>Comment</span><span>Share</span></div><div className="youtube-short-preview-overlay"><strong>{clipTitle}</strong><small>@ Your channel</small></div></div>
                <div className="youtube-short-preview-copy"><strong>{valueText(currentPackage.title) || 'Your YouTube title'}</strong><p>{valueText(currentPackage.description) || 'Your description will appear here.'}</p>{(Array.isArray(currentPackage.hashtags) ? currentPackage.hashtags : []).length > 0 && <small>{valueText(currentPackage.hashtags)}</small>}</div>
              </div>
              <p>YouTube may display Shorts differently across devices and app versions.</p>
            </section>
            <section className="youtube-publish-card" aria-label="Publish this export to YouTube">
            <div className="youtube-publish-heading"><span className="social-platform-card-icon"><PlatformIcon platform="youtube_shorts"/></span><div><strong>YouTube channel</strong><small>Upload this exact export version with the saved Shorts package.</small></div>
              {youtubeStatus?.connected ? <span className="youtube-connected-state"><CheckCircle2 size={14}/> Connected</span> : <span className="youtube-disconnected-state">Not connected</span>}
            </div>
            {!youtubeStatus?.configured && <p className="youtube-setup-hint">Place your downloaded Desktop OAuth JSON at <code>backend/secrets/youtube-oauth-client.json</code>, then restart the backend.</p>}
            {youtubeStatus?.configured && !youtubeStatus.connected && <div className="youtube-account-actions"><p>{waitingForYoutube ? 'Finish Google authorization in the browser window.' : 'Connect the Google account that manages your YouTube channel.'}</p><button className="button secondary" disabled={youtubeBusy || waitingForYoutube} onClick={() => void connectYoutube()}><ExternalLink size={14}/>{waitingForYoutube ? 'Waiting for Google...' : 'Connect YouTube'}</button></div>}
            {youtubeStatus?.connected && <>
              <div className="youtube-account-actions"><p>CLIPRA stores the authorization token encrypted for this Windows user. Disconnect any time to revoke it.</p><button className="button secondary small" disabled={youtubeBusy} onClick={() => void disconnectYoutube()}><Unplug size={13}/> Disconnect</button></div>
              <label className="youtube-privacy-field">Visibility<select value={youtubePrivacy} onChange={(event) => setYoutubePrivacy(event.target.value as YouTubeUpload['privacy_status'])} disabled={youtubeBusy}><option value="private">Private (only me)</option><option value="unlisted">Unlisted</option><option value="public">Public</option></select></label>
              <label className="youtube-publish-consent"><input type="checkbox" checked={youtubeConsent} onChange={(event) => setYoutubeConsent(event.target.checked)}/><span>I reviewed the saved title, description, and tags and approve uploading export V{version} to my channel as <strong>{youtubePrivacy}</strong>.</span></label>
              <button className="button primary youtube-upload-button" disabled={!youtubeConsent || hasUnsavedEdits || youtubeBusy || youtubeUploadActive} onClick={() => void uploadYoutube()}><Upload size={15}/> Upload export V{version} to YouTube</button>
              {hasUnsavedEdits && <small className="youtube-upload-note">Save or discard your package edits before uploading.</small>}
            </>}
            {youtubeUploads.filter((item) => item.generation_id === selected.id).map((item) => <div className="youtube-upload-result" key={item.id}>
              {(item.status === 'queued' || item.status === 'uploading') && <><div className="youtube-upload-progress-label"><span>{item.status === 'queued' ? 'Waiting to upload' : 'Uploading to YouTube'}</span><strong>{Math.round(item.progress * 100)}%</strong></div><progress max={1} value={item.progress}/><small>Do not close CLIPRA.AI until this upload finishes.</small></>}
              {item.status === 'completed' && <p className="youtube-upload-success"><CheckCircle2 size={15}/> Upload complete - {item.privacy_status}<a href={item.video_url ?? undefined} target="_blank" rel="noreferrer">Open on YouTube <ExternalLink size={12}/></a></p>}
              {(item.status === 'failed' || item.status === 'interrupted') && <p className="youtube-upload-error">{item.error_message}</p>}
            </div>)}
            <p className="youtube-upload-note"><ShieldCheck size={13}/> Uploading sends the rendered MP4 and saved YouTube package to Google/YouTube. CLIPRA never uploads without this button and per-upload approval.</p>
            </section>
          </>}
          {platform === 'instagram_reels' && <section className="youtube-publish-card instagram-publish-card" aria-label="Publish this export to Instagram Reels">
            <div className="youtube-publish-heading instagram-publish-heading"><span className="social-platform-card-icon"><PlatformIcon platform="instagram_reels"/></span><div><strong>Instagram Reels</strong><small>Publish this exact export version with its saved Instagram caption and hashtags.</small></div>
              {instagramStatus?.connected ? <span className="youtube-connected-state"><CheckCircle2 size={14}/> Connected</span> : <span className="youtube-disconnected-state">Not connected</span>}
            </div>
            {!instagramStatus?.configured && <p className="youtube-setup-hint">Configure the Meta app credentials at <code>backend/secrets/facebook-app.json</code>, then restart the backend.</p>}
            {instagramStatus?.connected && !instagramStatus.r2_storage_configured && <p className="youtube-setup-hint">Configure the Cloudflare R2 credentials in <code>backend/.env</code> before publishing Reels.</p>}
            {instagramStatus?.configured && !instagramStatus.connected && <div className="youtube-account-actions"><p>{waitingForInstagram ? 'Finish Meta authorization in the browser window.' : instagramStatus.message}</p><button className="button secondary" disabled={instagramBusy || waitingForInstagram} onClick={() => void connectInstagramAccount()}><ExternalLink size={14}/>{waitingForInstagram ? 'Waiting for Meta…' : instagramStatus.authorization_error ? 'Reconnect Meta' : 'Connect Instagram'}</button></div>}
            {instagramStatus?.connected && <>
              <div className="youtube-account-actions"><p>CLIPRA uses the linked Facebook Page connection to publish this Reel. Reconnect Meta if permissions or Page links change.</p></div>
              <label className="youtube-privacy-field">Instagram account<select aria-label="Instagram account" value={instagramAccountId} onChange={(event) => setInstagramAccountId(event.target.value)} disabled={instagramBusy}><option value="" disabled>Choose an Instagram account</option>{instagramStatus.accounts.map((account) => <option key={account.instagram_user_id} value={account.instagram_user_id}>@{account.instagram_username} · {account.page_name}</option>)}</select></label>
              <label className="youtube-publish-consent"><input type="checkbox" checked={instagramConsent} onChange={(event) => setInstagramConsent(event.target.checked)}/><span>I reviewed the saved caption and hashtags and approve publishing export V{version} as a Reel to <strong>@{instagramStatus.accounts.find((item) => item.instagram_user_id === instagramAccountId)?.instagram_username ?? 'the selected account'}</strong>.</span></label>
              <button className="button primary youtube-upload-button" disabled={!instagramConsent || !instagramAccountId || !instagramStatus.r2_storage_configured || hasUnsavedEdits || instagramBusy || instagramUploadActive} onClick={() => void publishInstagram()}><Upload size={15}/> Publish export V{version} to Instagram</button>
              {hasUnsavedEdits && <small className="youtube-upload-note">Save or discard package edits before publishing.</small>}
            </>}
            {instagramUploads.filter((item) => item.generation_id === selected.id).map((item) => <div className="youtube-upload-result" key={item.id}>
              {(item.status === 'queued' || item.status === 'uploading') && <><div className="youtube-upload-progress-label"><span>{item.status === 'queued' ? 'Waiting to publish' : `Publishing to @${item.instagram_username}`}</span><strong>{Math.round(item.progress * 100)}%</strong></div><progress max={1} value={item.progress}/><small>CLIPRA uploads a temporary MP4 copy to Cloudflare R2 so Meta can fetch it, then removes it after publishing.</small></>}
              {item.status === 'completed' && <p className="youtube-upload-success"><CheckCircle2 size={15}/> Reel published to @{item.instagram_username}{item.permalink && <a href={item.permalink} target="_blank" rel="noreferrer">Open on Instagram <ExternalLink size={12}/></a>}</p>}
              {(item.status === 'failed' || item.status === 'interrupted') && <p className="youtube-upload-error">{item.error_message}</p>}
            </div>)}
            <p className="youtube-upload-note"><ShieldCheck size={13}/> CLIPRA sends the completed MP4 and saved caption to Meta only after your approval. If a publish is interrupted, check Instagram before trying again.</p>
          </section>}
          {platform === 'facebook_reels' && <section className="youtube-publish-card facebook-publish-card" aria-label="Publish this export to a Facebook Page">
            <div className="youtube-publish-heading facebook-publish-heading"><span className="social-platform-card-icon"><PlatformIcon platform="facebook_reels"/></span><div><strong>Facebook Page</strong><small>Publish this exact export version as a Reel using its saved Facebook package.</small></div>
              {facebookStatus?.connected ? <span className="youtube-connected-state"><CheckCircle2 size={14}/> Connected</span> : <span className="youtube-disconnected-state">Not connected</span>}
            </div>
            {!facebookStatus?.configured && <p className="youtube-setup-hint">Place your Meta credentials at <code>backend/secrets/facebook-app.json</code>, then restart the backend.</p>}
            {facebookStatus?.configured && !facebookStatus.connected && <div className="youtube-account-actions"><p>{waitingForFacebook ? 'Finish Facebook authorization in the browser window.' : 'Connect the Facebook account that manages your Page.'}</p><button className="button secondary" disabled={facebookBusy || waitingForFacebook} onClick={() => void connectFacebookAccount()}><ExternalLink size={14}/>{waitingForFacebook ? 'Waiting for Facebook…' : 'Connect Facebook'}</button></div>}
            {facebookStatus?.connected && <>
              <div className="youtube-account-actions"><p>CLIPRA stores Page tokens encrypted for this Windows user. Disconnect clears them from this installation.</p><button className="button secondary small" disabled={facebookBusy} onClick={() => void disconnectFacebookAccount()}><Unplug size={13}/> Disconnect</button></div>
              <label className="youtube-privacy-field">Facebook Page<select aria-label="Facebook Page" value={facebookPageId} onChange={(event) => setFacebookPageId(event.target.value)} disabled={facebookBusy}><option value="" disabled>Choose a Page</option>{facebookStatus.pages.map((page) => <option key={page.id} value={page.id}>{page.name}</option>)}</select></label>
              <label className="youtube-publish-consent"><input type="checkbox" checked={facebookConsent} onChange={(event) => setFacebookConsent(event.target.checked)}/><span>I reviewed the saved caption and hashtags and approve publishing export V{version} as a Reel to <strong>{facebookStatus.pages.find((page) => page.id === facebookPageId)?.name ?? 'the selected Page'}</strong>.</span></label>
              <button className="button primary youtube-upload-button" disabled={!facebookConsent || !facebookPageId || hasUnsavedEdits || facebookBusy || facebookUploadActive} onClick={() => void publishFacebook()}><Upload size={15}/> Publish export V{version} to Facebook</button>
              {hasUnsavedEdits && <small className="youtube-upload-note">Save or discard package edits before publishing.</small>}
            </>}
            {facebookUploads.filter((item) => item.generation_id === selected.id).map((item) => <div className="youtube-upload-result" key={item.id}>
              {(item.status === 'queued' || item.status === 'uploading') && <><div className="youtube-upload-progress-label"><span>{item.status === 'queued' ? 'Waiting to upload' : `Uploading to ${item.page_name}`}</span><strong>{Math.round(item.progress * 100)}%</strong></div><progress max={1} value={item.progress}/><small>Keep CLIPRA.AI open until publishing finishes.</small></>}
              {item.status === 'completed' && <p className="youtube-upload-success"><CheckCircle2 size={15}/> Reel published to {item.page_name}<a href={item.video_url ?? undefined} target="_blank" rel="noreferrer">Open on Facebook <ExternalLink size={12}/></a></p>}
              {(item.status === 'failed' || item.status === 'interrupted') && <p className="youtube-upload-error">{item.error_message}</p>}
            </div>)}
            <p className="youtube-upload-note"><ShieldCheck size={13}/> CLIPRA uploads only after this approval. If an upload is interrupted, check the Page before retrying.</p>
          </section>}
          <p className="social-copy-note">Review every generated claim before posting. Suggested keywords and tags are ideas, not ranking guarantees.</p>
        </section>}
        {notice && <p className="social-content-notice" role="status"><Check size={13}/>{notice}</p>}
        {error && <p className="framing-error" role="alert">{error}</p>}
      </section>
    </div>
  </div>
}
