import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import ClipEditor from './ClipEditor'
import type { DraftClip, MediaAsset } from './api'

vi.mock('./CaptionPanel', () => ({ default: () => null }))
vi.mock('./CaptionOverlay', () => ({ default: () => null }))
vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()),
  saveClip: vi.fn(async (clip: DraftClip, fields: Partial<DraftClip>) => ({ ...clip, ...fields })),
}))

const media = { id: 'media', project_id: 'project', original_filename: 'fixture.mp4', size_bytes: 1, duration_seconds: 10, width: 1920, height: 1080, frame_rate: '30/1', frame_rate_decimal: 30, video_codec: 'h264', audio_codec: 'aac', has_audio: true, container_format: 'mp4', preview_status: 'not_requested', preview_error: null, imported_at: 'now', stream_url: '/source', preview_stream_url: '/preview' } as MediaAsset
const splitLayout: DraftClip['split_layout'] = { split_ratio: .5, top: { source_mode: 'same_video', image_asset_id: null, solid_color: '#151923', framing_mode: 'crop', zoom: 1, position_x: .5, position_y: .5, fit_background_color: '#090a0f' }, bottom: { framing_mode: 'crop', zoom: 1, position_x: .5, position_y: .5, fit_background_color: '#090a0f' } }
const clip = { id: 'clip', project_id: 'project', media_id: 'media', source_candidate_id: null, title: 'Test', start_seconds: 0, end_seconds: 5, workflow_status: 'draft', framing_mode: 'fit', recommended_framing_mode: null, manual_focus_x: .5, manual_focus_y: .5, manual_zoom: 1, blur_strength: 18, fit_background_color: '#090a0f', manual_override_enabled: false, layout_type: 'original', split_layout: splitLayout, framing_status: 'not_requested', framing_error_code: null, framing_error_message: null, framing_model: null, framing_requested_at: null, framing_completed_at: null, framing_start_seconds: null, framing_end_seconds: null, created_at: 'now', updated_at: 'now', focal_points: [] } as DraftClip

describe('ClipEditor split layout interactions', () => {
  it('keeps direct top and bottom preview positioning independent', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    render(<ClipEditor media={media} clip={clip} geminiConfigured={false} model="test" onClose={() => undefined} onSaved={() => undefined} onMediaUpdated={() => undefined}/> )
    fireEvent.change(screen.getByLabelText('Clip layout'), { target: { value: 'split_streamer_gameplay' } })
    const canvas = document.querySelector('canvas')!
    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, right: 360, bottom: 640, width: 360, height: 640, x: 0, y: 0, toJSON: () => ({}) })
    fireEvent.pointerDown(canvas, { clientX: 180, clientY: 120, pointerId: 1 })
    fireEvent.pointerMove(canvas, { clientX: 216, clientY: 120, pointerId: 1 })
    expect(screen.getByLabelText('Top horizontal position')).toHaveValue(0.4)
    fireEvent.pointerUp(canvas, { pointerId: 1 })
    fireEvent.click(screen.getByRole('tab', { name: 'Bottom' }))
    expect(screen.getByLabelText('Bottom horizontal position')).toHaveValue(0.5)
    fireEvent.pointerDown(canvas, { clientX: 180, clientY: 520, pointerId: 2 })
    fireEvent.pointerMove(canvas, { clientX: 216, clientY: 520, pointerId: 2 })
    expect(screen.getByLabelText('Bottom horizontal position')).toHaveValue(0.4)
    fireEvent.click(screen.getByRole('tab', { name: 'Top' }))
    expect(screen.getByLabelText('Top horizontal position')).toHaveValue(0.4)
  })

  it('offers a persisted solid-color source for the top panel', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    render(<ClipEditor media={media} clip={clip} geminiConfigured={false} model="test" onClose={() => undefined} onSaved={() => undefined} onMediaUpdated={() => undefined}/> )
    fireEvent.change(screen.getByLabelText('Clip layout'), { target: { value: 'split_streamer_gameplay' } })
    fireEvent.click(screen.getByRole('button', { name: 'Solid Color' }))
    expect(screen.getByLabelText('Top solid color')).toHaveValue('#151923')
  })

  it('offers independent source choices and trim for the bottom panel', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    render(<ClipEditor media={media} clip={clip} geminiConfigured={false} model="test" onClose={() => undefined} onSaved={() => undefined} onMediaUpdated={() => undefined}/> )
    fireEvent.change(screen.getByLabelText('Clip layout'), { target: { value: 'split_streamer_gameplay' } })
    fireEvent.click(screen.getByRole('tab', { name: 'Bottom' }))
    expect(screen.getByRole('button', { name: 'Same Video' })).toHaveClass('active')
    fireEvent.click(screen.getByRole('button', { name: 'Solid Color' }))
    expect(screen.getByLabelText('Bottom solid color')).toHaveValue('#151923')
    fireEvent.click(screen.getByRole('button', { name: 'Same Video' }))
    expect(screen.getByLabelText('Bottom vertical trim')).toHaveValue('0')
  })
})
