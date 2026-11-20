import { useRef, type KeyboardEvent, type PointerEvent } from 'react'
import { type BoundaryKey, type ClipBounds, clamp, updateBoundary } from './clipBoundaries'

type Props = {
  duration: number
  bounds: ClipBounds
  currentTime: number
  onBoundsChange: (bounds: ClipBounds) => void
}

export default function ClipRangeSelector({ duration, bounds, currentTime, onBoundsChange }: Props) {
  const trackRef = useRef<HTMLDivElement>(null)
  const activePointerRef = useRef<{ key: BoundaryKey; pointerId: number } | null>(null)

  const valueFromPointer = (clientX: number) => {
    const rect = trackRef.current?.getBoundingClientRect()
    if (!rect || rect.width <= 0 || duration <= 0) return 0
    return clamp(((clientX - rect.left) / rect.width) * duration, 0, duration)
  }

  const handlePointer = (key: BoundaryKey, event: PointerEvent<HTMLButtonElement>) => {
    event.preventDefault()
    const apply = (clientX: number) => onBoundsChange(updateBoundary(bounds, key, valueFromPointer(clientX), duration))
    apply(event.clientX)
    activePointerRef.current = { key, pointerId: event.pointerId }
    if (event.currentTarget.setPointerCapture) event.currentTarget.setPointerCapture(event.pointerId)
  }

  const movePointer = (key: BoundaryKey, event: PointerEvent<HTMLButtonElement>) => {
    if (activePointerRef.current?.key !== key || activePointerRef.current.pointerId !== event.pointerId) return
    onBoundsChange(updateBoundary(bounds, key, valueFromPointer(event.clientX), duration))
  }

  const releasePointer = (event: PointerEvent<HTMLButtonElement>) => {
    if (activePointerRef.current?.pointerId === event.pointerId) activePointerRef.current = null
  }

  const startPercent = duration ? bounds.start / duration * 100 : 0
  const endPercent = duration ? bounds.end / duration * 100 : 0
  const playheadPercent = duration ? clamp(currentTime / duration * 100, 0, 100) : 0
  const keyboardStep = Math.min(0.1, Math.max(0.01, duration / 1000))
  const handleKey = (key: BoundaryKey, event: KeyboardEvent<HTMLButtonElement>) => {
    let delta = 0
    if (event.key === 'ArrowLeft') delta = -keyboardStep
    if (event.key === 'ArrowRight') delta = keyboardStep
    if (!delta) return
    event.preventDefault()
    onBoundsChange(updateBoundary(bounds, key, key === 'start_seconds' ? bounds.start + delta : bounds.end + delta, duration))
  }

  return <div className="clip-range-selector" ref={trackRef} aria-label="Clip range selector">
    <div className="clip-range-track" />
    <div className="clip-range-selection" style={{ left: `${startPercent}%`, width: `${endPercent - startPercent}%` }} />
    <div className="clip-range-playhead" style={{ left: `${playheadPercent}%` }} aria-hidden="true" />
    <button type="button" role="slider" className="clip-range-handle start" aria-label="Clip start handle" aria-valuemin={0} aria-valuemax={Math.max(0, bounds.end)} aria-valuenow={bounds.start} style={{ left: `${startPercent}%` }} onPointerDown={(event) => handlePointer('start_seconds', event)} onPointerMove={(event) => movePointer('start_seconds', event)} onPointerUp={releasePointer} onPointerCancel={releasePointer} onKeyDown={(event) => handleKey('start_seconds', event)} />
    <button type="button" role="slider" className="clip-range-handle end" aria-label="Clip end handle" aria-valuemin={0} aria-valuemax={duration} aria-valuenow={bounds.end} style={{ left: `${endPercent}%` }} onPointerDown={(event) => handlePointer('end_seconds', event)} onPointerMove={(event) => movePointer('end_seconds', event)} onPointerUp={releasePointer} onPointerCancel={releasePointer} onKeyDown={(event) => handleKey('end_seconds', event)} />
  </div>
}
