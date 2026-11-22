import { useEffect, useRef, type CSSProperties, type PointerEvent } from 'react'
import type { CustomText } from './api'

type Props = { value: CustomText; editing?: boolean; onChange?: (patch: Partial<CustomText>) => void; clipStart?: number; currentSourceTime?: number }

export default function CustomTextOverlay({ value, editing = false, onChange, clipStart = 0, currentSourceTime = 0 }: Props) {
  const root = useRef<HTMLDivElement>(null)
  const textElement = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const element = textElement.current
    if (!element) return
    const elapsed = Math.max(0, currentSourceTime - clipStart) * 1000
    for (const animation of element.getAnimations()) {
      animation.pause()
      animation.currentTime = Math.min(elapsed, value.animation_ms || 140)
    }
  }, [clipStart, currentSourceTime, value.animation, value.animation_ms, value.enabled])
  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (!editing || !event.currentTarget.hasPointerCapture(event.pointerId)) return
    const rect = root.current?.getBoundingClientRect()
    if (!rect) return
    onChange?.({ position_x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), position_y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)) })
  }
  const style: CSSProperties & { WebkitTextStroke?: string; paintOrder?: string } = {
    left: `${value.position_x * 100}%`, top: `${value.position_y * 100}%`, width: 'max-content', maxWidth: '92%',
    fontFamily: value.font_family, fontWeight: value.font_weight, fontSize: `${Math.max(13, value.font_size / 3.9)}px`,
    color: value.text_color, textAlign: 'center', textShadow: 'none', animationDuration: `${value.animation_ms || 140}ms`,
    backgroundColor: value.background_opacity ? `color-mix(in srgb, ${value.background_color} ${value.background_opacity * 100}%, transparent)` : 'transparent',
    whiteSpace: 'pre-wrap',
  }
  const foregroundStyle: CSSProperties & { WebkitTextStroke?: string; paintOrder?: string } = {
    position: 'relative', zIndex: 1, color: value.text_color,
    textShadow: value.shadow_enabled ? `${value.shadow_x}px ${value.shadow_y}px ${value.shadow_blur}px ${value.shadow_color}` : 'none',
    WebkitTextStroke: value.stroke_enabled ? `${value.stroke_width}px ${value.stroke_color}` : '0 transparent', paintOrder: 'stroke fill',
  }
  if (!value.enabled || !value.text.trim()) return null
  return <div ref={root} className={`caption-overlay custom-text-overlay ${editing ? 'editing' : ''}`} onPointerDown={(event) => { if (!editing) return; event.currentTarget.setPointerCapture(event.pointerId); move(event) }} onPointerMove={move}>
    <div ref={textElement} className={`caption-text custom-text-content animation-${value.animation}`} style={style}>
      <span className="custom-text-foreground" style={foregroundStyle}>{value.text}</span>
    </div>
  </div>
}
