import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ClipRenderWorkflow from './ClipRenderWorkflow'
import type { DraftClip, RenderJob } from './api'

const { getRenderHistory, requestClipRenderPreview, approveRenderExport } = vi.hoisted(() => ({
  getRenderHistory: vi.fn(), requestClipRenderPreview: vi.fn(), approveRenderExport: vi.fn(),
}))
vi.mock('./api', async (importOriginal) => ({ ...(await importOriginal<typeof import('./api')>()), getRenderHistory, requestClipRenderPreview, approveRenderExport }))

const clip = { id: 'clip-1', title: 'Demo' } as DraftClip
const preview: RenderJob = { id: 'preview-1', clip_id: 'clip-1', project_id: 'project-1', kind: 'preview', status: 'completed', config_hash: 'hash', progress: 1, stage: 'completed', error_message: null, output_bytes: 100, version_number: null, approved_at: null, created_at: '2026-01-01', completed_at: '2026-01-01', stream_url: '/api/render-jobs/preview-1/stream', download_url: null, current: true }
const queuedExport: RenderJob = { ...preview, id: 'export-1', kind: 'export', status: 'queued', progress: 0, stage: 'queued', version_number: 1, stream_url: null, download_url: null, current: false }

describe('ClipRenderWorkflow', () => {
  beforeEach(() => { vi.clearAllMocks(); getRenderHistory.mockResolvedValue([]) })

  it('requires a fresh preview before approval and sends explicit export approval', async () => {
    requestClipRenderPreview.mockResolvedValue(preview)
    getRenderHistory.mockResolvedValueOnce([]).mockResolvedValue([preview])
    approveRenderExport.mockResolvedValue(queuedExport)
    render(<ClipRenderWorkflow clip={clip} captionTrackId={null} onEdit={vi.fn()}/>)
    expect(screen.getByRole('button', { name: /approve & export/i })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: /generate fresh preview/i }))
    await waitFor(() => expect(screen.getByRole('button', { name: /approve & export/i })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: /approve & export/i }))
    await waitFor(() => expect(approveRenderExport).toHaveBeenCalledWith('preview-1'))
  })

  it('returns to the editor using Reopen in Editor', () => {
    const onEdit = vi.fn()
    render(<ClipRenderWorkflow clip={clip} captionTrackId={null} onEdit={onEdit}/>)
    fireEvent.click(screen.getByRole('button', { name: /reopen in editor/i }))
    expect(onEdit).toHaveBeenCalledOnce()
  })
})
