import { describe, expect, it } from 'vitest'
import { clampSplitRatio, DEFAULT_SPLIT_LAYOUT, splitSectionHeights, splitSourceDrawRect, updateSectionPosition } from './splitLayout'

describe('split layout geometry', () => {
  it('clamps the divider and keeps both pane heights inside the canvas', () => {
    expect(clampSplitRatio(0)).toBe(.25)
    expect(clampSplitRatio(1)).toBe(.75)
    expect(splitSectionHeights(640, .4)).toEqual({ top: 256, bottom: 384 })
  })

  it('changes a dragged section position without changing the other section', () => {
    const moved = updateSectionPosition(DEFAULT_SPLIT_LAYOUT, 'top', 20, -10, 100, 100)
    expect(moved.top.position_x).toBeCloseTo(.3)
    expect(moved.top.position_y).toBeCloseTo(.6)
    expect(moved.bottom).toEqual(DEFAULT_SPLIT_LAYOUT.bottom)
  })

  it('applies zoom to crop, fit, and image source geometry', () => {
    const cropOne = splitSourceDrawRect(160, 90, 180, 100, { ...DEFAULT_SPLIT_LAYOUT.top, zoom: 1 })
    const cropTwo = splitSourceDrawRect(160, 90, 180, 100, { ...DEFAULT_SPLIT_LAYOUT.top, zoom: 2 })
    expect(cropTwo.width).toBeGreaterThan(cropOne.width)
    expect(cropTwo.height).toBeGreaterThan(cropOne.height)
    const fit = splitSourceDrawRect(160, 90, 180, 100, { ...DEFAULT_SPLIT_LAYOUT.top, framing_mode: 'fit', zoom: 2 })
    expect(fit.width).toBeGreaterThan(180)
    expect(fit.height).toBeGreaterThan(100)
  })
})
