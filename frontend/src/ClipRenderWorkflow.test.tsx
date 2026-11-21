import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ClipRenderWorkflow from './ClipRenderWorkflow'
import type { DraftClip, RenderJob } from './api'

const { getRenderHistory, requestClipExport } = vi.hoisted(() => ({
  getRenderHistory: vi.fn(), requestClipExport: vi.fn(),
}))
vi.mock('./api', async (importOriginal) => ({ ...(await importOriginal<typeof import('./api')>()), getRenderHistory, requestClipExport }))

const clip = { id: 'clip-1', title: 'Demo' } as DraftClip
const queuedExport: RenderJob = { id: 'export-1', clip_id: 'clip-1', project_id: 'project-1', kind: 'export', status: 'queued', config_hash: 'hash', progress: 0, stage: 'queued', error_message: null, output_bytes: null, version_number: 1, approved_at: '2026-01-01', created_at: '2026-01-01', completed_at: null, stream_url: null, download_url: null, current: false, resolution: '1080' }

describe('ClipRenderWorkflow', () => {
  beforeEach(() => { vi.clearAllMocks(); getRenderHistory.mockResolvedValue([]) })

  it('starts one explicitly approved export without a preview render step', async () => {
    requestClipExport.mockResolvedValue(queuedExport)
    render(<ClipRenderWorkflow clip={clip} captionTrackId={null} sourceWidth={1920} sourceHeight={1080} onEdit={vi.fn()}/> )
    expect(screen.queryByText(/generate fresh preview|approve & export/i)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Export V1' }))
    await waitFor(() => expect(requestClipExport).toHaveBeenCalledWith('clip-1', null, '1080'))
    expect(await screen.findByText(/queued/i)).toBeInTheDocument()
  })

  it('returns to the editor using Reopen in Editor', () => {
    const onEdit = vi.fn()
    render(<ClipRenderWorkflow clip={clip} captionTrackId={null} sourceWidth={1920} sourceHeight={1080} onEdit={onEdit}/> )
    fireEvent.click(screen.getByRole('button', { name: /reopen in editor/i }))
    expect(onEdit).toHaveBeenCalledOnce()
  })
})
