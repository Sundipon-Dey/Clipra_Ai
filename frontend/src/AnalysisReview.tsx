import { AlertCircle, CircleAlert, LoaderCircle, Play, Sparkles } from 'lucide-react'
import type { AnalysisRun, HighlightCandidate, MediaAsset } from './api'

type Props = {
  media: MediaAsset
  runs: AnalysisRun[]
  geminiConfigured: boolean
  onAnalyze: () => void
  onPreview: (startSeconds: number, endSeconds: number) => void
  onCreateClip: (candidate: HighlightCandidate) => void
}

const activeStatuses = ['queued', 'uploading', 'processing_file', 'analyzing']

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    queued: 'Queued', uploading: 'Uploading to Google', processing_file: 'Google processing video',
    analyzing: 'Finding highlights', completed: 'Analysis complete', failed: 'Analysis failed',
    interrupted: 'Interrupted by restart',
  }
  return labels[status] ?? status
}

function timestamp(seconds: number) {
  const minutes = Math.floor(seconds / 60)
  return minutes + ':' + (seconds - minutes * 60).toFixed(1).padStart(4, '0')
}

export default function AnalysisReview({ media, runs, geminiConfigured, onAnalyze, onPreview, onCreateClip }: Props) {
  const active = runs.find((run) => activeStatuses.includes(run.status))
  const latest = runs[0]
  return (
    <section className="analysis-review">
      <div className="analysis-action">
        <button className="button ai-button small" disabled={!geminiConfigured || Boolean(active)} onClick={onAnalyze}>
          {active ? <><LoaderCircle size={13} className="spin" /> {statusLabel(active.status)}</> : <><Sparkles size={13} /> {latest ? 'Run analysis again' : 'Analyze with Gemini'}</>}
        </button>
        {!geminiConfigured && <small>Gemini is not configured.</small>}
      </div>
      {runs.map((run) => (
        <section className="analysis-panel" key={run.id}>
          <div className="analysis-panel-heading">
            <div><span className={'analysis-status ' + run.status}><i />{statusLabel(run.status)}</span><span className="analysis-model">{run.model_name}</span></div>
            {run.cleanup_pending && <span className="cleanup-note"><CircleAlert size={13} /> Cleanup pending · Google expires temporary files automatically</span>}
          </div>
          {run.error_message && <p className="analysis-error" role="alert"><AlertCircle size={14} />{run.error_message}</p>}
          {run.status === 'completed' && run.candidates.length === 0 && <p className="analysis-empty">No valid highlight suggestions were found in this run.</p>}
          {run.candidates.map((candidate) => (
            <div className="candidate-card" key={candidate.id}>
              <div className="candidate-time"><span>{timestamp(candidate.start_seconds)}–{timestamp(candidate.end_seconds)}</span><div><button className="text-button" onClick={() => onPreview(candidate.start_seconds, candidate.end_seconds)}><Play size={13} /> Preview moment</button><button className="text-button" onClick={() => onCreateClip(candidate)}>Edit as clip</button></div></div>
              <div className="candidate-title-line"><h3>{candidate.title}</h3><span className="category-pill">{candidate.category}</span></div>
              <p>{candidate.description}</p><small>{candidate.reasoning}</small>
              {candidate.confidence !== null && <span className="confidence-note">AI confidence estimate {Math.round(candidate.confidence * 100)}% · subjective</span>}
            </div>
          ))}
          <span className="analysis-history-time">Run {new Date(run.created_at).toLocaleString()}</span>
        </section>
      ))}
      <span className="sr-only">{media.original_filename}</span>
    </section>
  )
}
