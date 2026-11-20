export const MIN_CLIP_DURATION = 0.04

export type BoundaryKey = 'start_seconds' | 'end_seconds'
export type ClipBounds = { start: number; end: number }

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

export function isValidBounds(start: number, end: number, duration: number) {
  return Number.isFinite(start) && Number.isFinite(end) && Number.isFinite(duration)
    && start >= 0 && end > start && end <= duration && end - start >= MIN_CLIP_DURATION
}

export function updateBoundary(bounds: ClipBounds, key: BoundaryKey, value: number, duration: number): ClipBounds {
  if (!Number.isFinite(value) || !Number.isFinite(duration) || duration < MIN_CLIP_DURATION) return bounds
  if (key === 'start_seconds') {
    return { start: clamp(value, 0, bounds.end - MIN_CLIP_DURATION), end: bounds.end }
  }
  return { start: bounds.start, end: clamp(value, bounds.start + MIN_CLIP_DURATION, duration) }
}

export function boundaryError(startText: string, endText: string, duration: number): string | null {
  const start = Number(startText)
  const end = Number(endText)
  if (!startText.trim() || !endText.trim() || !Number.isFinite(start) || !Number.isFinite(end)) return 'Enter numeric start and end times.'
  if (start < 0) return 'Start must be 0 seconds or later.'
  if (end <= start) return 'End must be after start.'
  if (end > duration) return `End must be within the ${formatTimestamp(duration)} source duration.`
  if (end - start < MIN_CLIP_DURATION) return `Clip duration must be at least ${MIN_CLIP_DURATION.toFixed(2)} seconds.`
  return null
}

export function formatInputSeconds(seconds: number) {
  return seconds.toFixed(3).replace(/\.?0+$/, '') || '0'
}

export function formatTimestamp(seconds: number) {
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${(seconds % 60).toFixed(2).padStart(5, '0')}`
}
