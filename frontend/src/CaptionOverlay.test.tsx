import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import CaptionOverlay from './CaptionOverlay'
import type { CaptionTrack } from './api'

const track: CaptionTrack = {
  id: 'track-1', clip_id: 'clip-1', transcription_run_id: null, name: 'Captions', language: 'en', preset_id: 'gaming_pulse', style_version: 1,
  style: { name: 'Gaming Pulse', font_family: 'Arial Black', font_weight: 900, font_size: 76, text_color: '#ffffff', highlight_color: '#00ffff', outline_color: '#000000', outline_width: 4, shadow_color: '#000000', shadow_offset: 3, background_color: '#000000', background_opacity: 0, alignment: 'center', animation: 'pop_karaoke', animation_ms: 120 },
  grouping: { max_words_per_line: 4, max_lines: 2, max_cue_seconds: 3, pause_seconds: .45 }, position_x: .5, position_y: .7, safe_zone_profile: 'shorts', timing_offset_seconds: 0, boundary_start_seconds: 0, boundary_end_seconds: 10, stale: false, created_at: '', updated_at: '',
  segments: [{ id: 'segment-1', ordinal: 0, start_seconds: 1, end_seconds: 3, generated_text: 'Hello world', override_text: null, manually_edited: false, words: [{ id: 'word-1', ordinal: 0, start_seconds: 1, end_seconds: 1.8, original_text: 'Hello', text: 'Hello', confidence: .9 }, { id: 'word-2', ordinal: 1, start_seconds: 1.8, end_seconds: 3, original_text: 'world', text: 'world', confidence: .9 }] }],
}

describe('caption overlay', () => {
  it('pops active words even when the selected preset has no cue animation', () => {
    const minimalTrack = { ...track, style: { ...track.style, animation: 'none' as const, animation_ms: 0 } }
    render(<CaptionOverlay track={minimalTrack} clipStart={0} currentSourceTime={1.4} editing onPosition={() => undefined}/> )
    expect(screen.getByText('Hello')).toHaveClass('active-word-pop')
    expect((screen.getByText('Hello') as HTMLElement).style.animationDuration).toBe('120ms')
  })

  it('marks each newly spoken word for its pop animation', () => {
    const { rerender } = render(<CaptionOverlay track={track} clipStart={0} currentSourceTime={1.4} editing onPosition={() => undefined}/> )
    expect(screen.getByText('Hello')).toHaveClass('active-word-pop')
    rerender(<CaptionOverlay track={track} clipStart={0} currentSourceTime={2} editing onPosition={() => undefined}/> )
    expect(screen.getByText('world')).toHaveClass('active-word-pop')
    expect(screen.getByText('Hello')).not.toHaveClass('active-word-pop')
  })

  it('shows the active word and persists one normalized position at the end of a pointer drag', () => {
    const moved = vi.fn()
    render(<CaptionOverlay track={track} clipStart={0} currentSourceTime={1.4} editing onPosition={moved}/>)
    expect(screen.getByText('Hello')).toHaveClass('active-word')
    expect(screen.getByText('Hello')).toHaveClass('active-word-pop')
    const overlay = document.querySelector('.caption-overlay') as HTMLDivElement
    vi.spyOn(overlay, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, right: 200, bottom: 400, width: 200, height: 400, x: 0, y: 0, toJSON: () => ({}) })
    fireEvent.pointerDown(overlay, { clientX: 100, clientY: 240, pointerId: 1 })
    fireEvent.pointerMove(overlay, { clientX: 140, clientY: 200, pointerId: 1 })
    fireEvent.pointerUp(overlay, { clientX: 140, clientY: 200, pointerId: 1 })
    expect(moved).toHaveBeenLastCalledWith(.7, .5, true)
  })
})
