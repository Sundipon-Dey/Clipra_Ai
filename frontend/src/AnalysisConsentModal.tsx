import { CircleAlert, LoaderCircle, Sparkles, X } from 'lucide-react'
import type { MediaAsset } from './api'

type Props = {
  media: MediaAsset
  model: string
  maxBytes: number
  configured: boolean
  busy: boolean
  onCancel: () => void
  onConfirm: () => void
}

function size(bytes: number) {
  if (bytes >= 1024 ** 3) return (bytes / 1024 ** 3).toFixed(1) + ' GB'
  return (bytes / 1024 ** 2).toFixed(1) + ' MB'
}

export default function AnalysisConsentModal({ media, model, maxBytes, configured, busy, onCancel, onConfirm }: Props) {
  const tooLarge = media.size_bytes > maxBytes
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onCancel() }}>
      <section className="analysis-confirm-modal" role="dialog" aria-modal="true" aria-labelledby="analysis-confirm-title">
        <header><span className="analysis-confirm-icon"><Sparkles size={18} /></span><button className="icon-button" onClick={onCancel} disabled={busy} aria-label="Close"><X size={18} /></button></header>
        <p className="eyebrow">EXTERNAL AI ANALYSIS</p><h2 id="analysis-confirm-title">Send this video to Gemini?</h2>
        <p className="confirm-file-name">{media.original_filename}</p>
        <div className="confirm-warning"><CircleAlert size={16} /><p>CLIPRA will upload its managed copy of this video to Google Gemini Files API for analysis. Your original source file remains unchanged. Google stores the analysis interaction while it runs; CLIPRA deletes that record and the temporary video after completion where possible. API usage is subject to your account quota and may be billable; CLIPRA cannot guarantee free-tier availability.</p></div>
        <small>Model: {model} · Video size: {size(media.size_bytes)} · max upload: {size(maxBytes)}</small>
        {!configured && <p className="analysis-error">Gemini is not configured. Add GEMINI_API_KEY to backend/.env and restart.</p>}
        {tooLarge && <p className="analysis-error">This video exceeds the configured Gemini per-file upload limit.</p>}
        <div className="modal-actions"><button className="button secondary" onClick={onCancel} disabled={busy}>Cancel</button><button className="button primary" onClick={onConfirm} disabled={busy || !configured || tooLarge}>{busy ? <><LoaderCircle size={15} className="spin" /> Starting…</> : <><Sparkles size={15} /> Upload and analyze</>}</button></div>
      </section>
    </div>
  )
}
