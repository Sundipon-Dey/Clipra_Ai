import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import ClipRangeSelector from './ClipRangeSelector'
import { MIN_CLIP_DURATION, boundaryError, updateBoundary } from './clipBoundaries'

function Harness() {
  const [bounds, setBounds] = useState({ start: 2, end: 8 })
  return <><ClipRangeSelector duration={10} bounds={bounds} currentTime={4} onBoundsChange={setBounds}/><output>{bounds.start.toFixed(2)}-{bounds.end.toFixed(2)}</output></>
}

describe('clip range boundaries', () => {
  it('moves the start handle from mouse pointer input and keeps the end synchronized', () => {
    render(<Harness />)
    const selector = screen.getByLabelText('Clip range selector')
    vi.spyOn(selector, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, right: 200, bottom: 31, width: 200, height: 31, x: 0, y: 0, toJSON: () => ({}) })
    const handle = screen.getByRole('slider', { name: 'Clip start handle' })
    fireEvent.pointerDown(handle, { clientX: 40, pointerId: 1, pointerType: 'mouse' })
    fireEvent.pointerMove(handle, { clientX: 60, pointerId: 1, pointerType: 'mouse' })
    fireEvent.pointerUp(handle, { pointerId: 1, pointerType: 'mouse' })
    expect(screen.getByText('3.00-8.00')).toBeInTheDocument()
  })

  it('moves the end handle from touch pointer input', () => {
    render(<Harness />)
    const selector = screen.getByLabelText('Clip range selector')
    vi.spyOn(selector, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, right: 200, bottom: 31, width: 200, height: 31, x: 0, y: 0, toJSON: () => ({}) })
    const handle = screen.getByRole('slider', { name: 'Clip end handle' })
    fireEvent.pointerDown(handle, { clientX: 160, pointerId: 2, pointerType: 'touch' })
    fireEvent.pointerMove(handle, { clientX: 180, pointerId: 2, pointerType: 'touch' })
    fireEvent.pointerUp(handle, { pointerId: 2, pointerType: 'touch' })
    expect(screen.getByText('2.00-9.00')).toBeInTheDocument()
  })

  it('prevents handles from crossing and reports invalid typed boundaries', () => {
    expect(updateBoundary({ start: 2, end: 8 }, 'start_seconds', 12, 10)).toEqual({ start: 7.96, end: 8 })
    expect(updateBoundary({ start: 2, end: 8 }, 'end_seconds', 0, 10)).toEqual({ start: 2, end: 2 + MIN_CLIP_DURATION })
    expect(boundaryError('8', '2', 10)).toBe('End must be after start.')
    expect(boundaryError('0', '12', 10)).toContain('within')
  })
})
