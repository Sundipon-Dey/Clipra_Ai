import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import ClipEditor from './ClipEditor'
import { saveClip, type DraftClip, type MediaAsset } from './api'

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return {
    ...actual,
    getClip: vi.fn(),
    requestFramingSuggestion: vi.fn(),
    requestPreview: vi.fn(),
    saveClip: vi.fn(async (clip: DraftClip, fields: Partial<DraftClip>) => ({ ...clip, ...fields })),
  }
})

const media: MediaAsset = {
  id: 'media-1', project_id: 'project-1', original_filename: 'source.mp4', size_bytes: 1,
  duration_seconds: 10, width: 1920, height: 1080, frame_rate: '30', frame_rate_decimal: 30,
  video_codec: 'h264', audio_codec: 'aac', has_audio: true, container_format: 'mp4',
  preview_status: 'not_requested', preview_error: null, imported_at: '2026-01-01T00:00:00Z',
  stream_url: '/api/media/media-1/stream', preview_stream_url: '/api/media/media-1/preview/stream',
}

const clip: DraftClip = {
  id: 'clip-1', project_id: 'project-1', media_id: 'media-1', source_candidate_id: null,
  title: 'Draft', start_seconds: 2, end_seconds: 8, workflow_status: 'draft', framing_mode: 'fit',
  recommended_framing_mode: null, manual_focus_x: .5, manual_focus_y: .5, manual_zoom: 1, blur_strength: 18, fit_background_color: '#090a0f',
  framing_status: 'not_requested', framing_error_code: null, framing_error_message: null, framing_model: null,
  framing_requested_at: null, framing_completed_at: null, framing_start_seconds: null, framing_end_seconds: null,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', focal_points: [], manual_override_enabled: false,
  layout_type: 'original', split_layout: { split_ratio: .5, top: { source_mode: 'same_video', image_asset_id: null, solid_color: '#151923', framing_mode: 'crop', zoom: 1, position_x: .5, position_y: .5, fit_background_color: '#090a0f' }, bottom: { framing_mode: 'crop', zoom: 1, position_x: .5, position_y: .5, fit_background_color: '#090a0f' } },
}

describe('ClipEditor boundary synchronization', () => {
  it('synchronizes timeline dragging, text entry, validation, and saved clip boundaries', async () => {
    const onSaved = vi.fn()
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    render(<ClipEditor media={media} clip={clip} geminiConfigured={false} model="test" onClose={() => undefined} onSaved={onSaved} onMediaUpdated={() => undefined}/>)

    const selector = screen.getByLabelText('Clip range selector')
    vi.spyOn(selector, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, right: 200, bottom: 31, width: 200, height: 31, x: 0, y: 0, toJSON: () => ({}) })
    fireEvent.pointerDown(screen.getByRole('slider', { name: 'Clip end handle' }), { clientX: 180, pointerId: 1, pointerType: 'mouse' })
    expect(screen.getByRole('textbox', { name: 'End (seconds)' })).toHaveValue('9')

    const start = screen.getByRole('textbox', { name: 'Start (seconds)' })
    fireEvent.change(start, { target: { value: '1.125' } })
    expect(screen.getByRole('slider', { name: 'Clip start handle' })).toHaveAttribute('aria-valuenow', '1.125')
    expect(screen.getByText('Selected 0:07.88')).toBeInTheDocument()

    fireEvent.change(start, { target: { value: '9' } })
    expect(screen.getByRole('alert')).toHaveTextContent('End must be after start.')
    expect(screen.getByRole('button', { name: /Save draft/i })).toBeDisabled()
    fireEvent.change(start, { target: { value: '1.125' } })
    fireEvent.click(screen.getByRole('button', { name: /Save draft/i }))

    await waitFor(() => expect(saveClip).toHaveBeenCalledWith(expect.objectContaining({ id: 'clip-1' }), expect.objectContaining({ start_seconds: 1.125, end_seconds: 9 })))
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ start_seconds: 1.125, end_seconds: 9 }))
  })
})
