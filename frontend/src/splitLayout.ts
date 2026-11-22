import type { SplitLayout } from './api'

export const DEFAULT_SPLIT_LAYOUT: SplitLayout = {
  split_ratio: 0.5,
  top: { source_mode: 'same_video', image_asset_id: null, solid_color: '#151923', framing_mode: 'crop', vertical_crop_percent: 0, zoom: 1, position_x: 0.5, position_y: 0.5, fit_background_color: '#090a0f' },
  bottom: { source_mode: 'same_video', image_asset_id: null, solid_color: '#151923', framing_mode: 'crop', vertical_crop_percent: 0, zoom: 1, position_x: 0.5, position_y: 0.5, fit_background_color: '#090a0f' },
}

export type SplitSectionKey = 'top' | 'bottom'

export function splitSourceDrawRect(sourceWidth: number, sourceHeight: number, width: number, height: number, section: SplitLayout['top'] | SplitLayout['bottom']) {
  const zoom = Math.max(1, Math.min(10, section.zoom))
  const virtualWidth = width * zoom, virtualHeight = height * zoom
  const scale = section.framing_mode === 'crop'
    ? Math.max(virtualWidth / sourceWidth, virtualHeight / sourceHeight)
    : Math.min(virtualWidth / sourceWidth, virtualHeight / sourceHeight)
  const drawWidth = sourceWidth * scale, drawHeight = sourceHeight * scale
  return {
    x: section.framing_mode === 'crop' ? -(drawWidth - width) * section.position_x : (width - drawWidth) * section.position_x,
    y: section.framing_mode === 'crop' ? -(drawHeight - height) * section.position_y : (height - drawHeight) * section.position_y,
    width: drawWidth,
    height: drawHeight,
  }
}

export function clampSplitRatio(value: number): number {
  return Math.max(0.25, Math.min(0.75, value))
}

export function updateSectionPosition(layout: SplitLayout, key: SplitSectionKey, deltaX: number, deltaY: number, width: number, height: number): SplitLayout {
  const section = layout[key]
  const position = {
    position_x: Math.max(0, Math.min(1, section.position_x - deltaX / Math.max(1, width))),
    position_y: Math.max(0, Math.min(1, section.position_y - deltaY / Math.max(1, height))),
  }
  return key === 'top'
    ? { ...layout, top: { ...layout.top, ...position } }
    : { ...layout, bottom: { ...layout.bottom, ...position } }
}

export function splitSectionHeights(height: number, ratio: number): { top: number; bottom: number } {
  const top = Math.round(height * clampSplitRatio(ratio))
  return { top, bottom: height - top }
}
