import { useRef, type CSSProperties } from 'react'
import type { CaptionTrack } from './api'

type Props = { track: CaptionTrack | null; clipStart: number; currentSourceTime: number; editing: boolean; onPosition: (x: number, y: number, commit: boolean) => void; canvasPassthrough?: boolean }

const safeZones = { shorts: { top: .08, bottom: .17 }, reels: { top: .1, bottom: .18 }, tiktok: { top: .1, bottom: .22 }, facebook: { top: .08, bottom: .17 } }

export default function CaptionOverlay({ track, clipStart, currentSourceTime, editing, onPosition, canvasPassthrough = false }: Props) {
  const overlay = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  if (!track) return null
  const relative = currentSourceTime - clipStart + track.timing_offset_seconds
  const segment = track.segments.find((item) => relative >= item.start_seconds && relative < item.end_seconds)
  const activeWord = segment?.words.find((word) => relative >= word.start_seconds && relative < word.end_seconds)
  const oneWordMode = track.grouping.display_mode === 'one_word'
  const style = track.style
  // Word emphasis is independent of the preset's cue-entry animation. This keeps
  // the spoken-word pop present for every preset, including karaoke/fade styles.
  const wordPop = !oneWordMode
  const wordPopDuration = `${style.animation_ms || 120}ms`
  const captionAnimation = oneWordMode && style.animation.startsWith('pop') ? 'none' : style.animation
  const position = (event: React.PointerEvent<HTMLDivElement>, commit = false) => {
    if (!editing) return
    const rect = overlay.current?.getBoundingClientRect()
    if (!rect) return
    event.preventDefault()
    event.currentTarget.setPointerCapture?.(event.pointerId)
    let x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
    let y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))
    if (Math.abs(x - .5) <= .025) x = .5
    if (Math.abs(y - .5) <= .025) y = .5
    if (commit) dragging.current = false
    onPosition(x, y, commit)
  }
  const move = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!editing || !event.currentTarget.hasPointerCapture?.(event.pointerId)) return
    position(event)
  }
  const zone = safeZones[track.safe_zone_profile]
  return <div ref={overlay} className={`caption-overlay ${editing ? 'editing' : ''} ${canvasPassthrough ? 'canvas-passthrough' : ''} ${dragging.current ? 'dragging' : ''}`} onPointerDown={(event) => { dragging.current = true; position(event) }} onPointerMove={move} onPointerUp={(event) => position(event, true)} onPointerCancel={(event) => position(event, true)}>
    {editing && <><i className="caption-safe-zone top" style={{ height: `${zone.top * 100}%` }}/><i className="caption-safe-zone bottom" style={{ height: `${zone.bottom * 100}%` }}/></>}
    {editing && dragging.current && <><i className="caption-align-guide vertical"/><i className="caption-align-guide horizontal"/></>}
    {segment && (!oneWordMode || activeWord) && <div key={oneWordMode ? activeWord?.id : segment.id} className={`caption-text animation-${captionAnimation}${oneWordMode ? ' caption-one-word' : ''}`} style={{ left: `${track.position_x * 100}%`, top: `${track.position_y * 100}%`, width: 'max-content', maxWidth: '92%', fontFamily: style.font_family, fontWeight: style.font_weight, fontSize: `${Math.max(13, style.font_size / 3.9)}px`, color: style.text_color, textAlign: style.alignment, textShadow: `${style.shadow_offset / 2}px ${style.shadow_offset / 2}px 0 ${style.shadow_color}`, animationDuration: `${style.animation_ms || 140}ms`, backgroundColor: style.background_opacity ? (style.background_color.toLowerCase() === '#ffffff' ? `rgba(255,255,255,${style.background_opacity})` : `rgba(0,0,0,${style.background_opacity})`) : 'transparent' } as CSSProperties}>
      {oneWordMode ? <span key={activeWord?.id} className="active-word active-word-pop" style={{ color: style.highlight_color, animationDuration: wordPopDuration }}>{activeWord?.text.replace(/[.,]/g, '')}</span> : (segment.override_text ?? segment.generated_text).split(/(\s+)/).map((token, index) => {
        const active = Boolean(activeWord && token.trim() === activeWord.text.trim())
        return <span key={active ? `${index}-${activeWord?.id}` : index} className={active ? `active-word${wordPop ? ' active-word-pop' : ''}` : ''} style={active ? { color: style.highlight_color, animationDuration: wordPopDuration } : undefined}>{token}</span>
      })}
    </div>}
  </div>
}
