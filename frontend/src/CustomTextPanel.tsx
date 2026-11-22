import { RotateCcw } from 'lucide-react'
import type { CustomText } from './api'
import { captionPresets } from './captionPresets'

type Props = { value: CustomText; onChange: (patch: Partial<CustomText>) => void }
const preferredEffects = { stroke_enabled: false, stroke_width: 4, stroke_color: '#000000', shadow_enabled: true, shadow_blur: 5, shadow_color: '#000000', shadow_x: 3, shadow_y: 3 } satisfies Partial<CustomText>

export default function CustomTextPanel({ value, onChange }: Props) {
  const choosePreset = (presetId: string) => {
    const style = captionPresets[presetId]
    onChange({ preset_id: presetId, font_family: style.font_family, font_weight: style.font_weight, font_size: style.font_size, text_color: style.text_color, background_color: style.background_color, background_opacity: style.background_opacity, animation: style.animation, animation_ms: style.animation_ms, stroke_enabled: style.outline_width > 0, stroke_width: style.outline_width, stroke_color: style.outline_color, shadow_enabled: style.shadow_offset > 0, shadow_blur: style.shadow_offset, shadow_color: style.shadow_color, shadow_x: style.shadow_offset / 2, shadow_y: style.shadow_offset / 2 })
  }
  return <div className="custom-text-panel">
    <div className="custom-text-heading"><div><p className="eyebrow">CUSTOM TEXT</p><h3>Add text to your clip</h3></div><label className="custom-text-enabled"><input type="checkbox" checked={value.enabled} onChange={(event) => onChange({ enabled: event.target.checked })}/> Show text</label></div>
    <label className="editor-field">Text<textarea value={value.text} maxLength={1000} rows={3} placeholder="Type text to show over your video" onChange={(event) => onChange({ text: event.target.value })}/></label>
    <p className="custom-text-help">Drag the text in the preview to position it. Presets affect this text only.</p>
    <div className="preset-grid custom-text-presets" aria-label="Custom text style presets">{Object.entries(captionPresets).map(([id, style]) => <button type="button" key={id} className={value.preset_id === id ? 'caption-preset active' : 'caption-preset'} onClick={() => choosePreset(id)}><strong>{style.name}</strong><small>{style.animation.replace('_', ' ')}</small></button>)}</div>
    <div className="custom-text-control-grid">
      <label>Size <strong>{value.font_size}</strong><input type="range" min="18" max="160" value={value.font_size} onChange={(event) => onChange({ font_size: Number(event.target.value) })}/></label>
      <label>Text color<input type="color" value={value.text_color} onChange={(event) => onChange({ text_color: event.target.value })}/></label>
      <label>Horizontal position <strong>{Math.round(value.position_x * 100)}%</strong><input type="range" min="0" max="100" value={Math.round(value.position_x * 100)} onChange={(event) => onChange({ position_x: Number(event.target.value) / 100 })}/></label>
      <label>Vertical position <strong>{Math.round(value.position_y * 100)}%</strong><input type="range" min="0" max="100" value={Math.round(value.position_y * 100)} onChange={(event) => onChange({ position_y: Number(event.target.value) / 100 })}/></label>
    </div>
    <fieldset className="custom-effect-fieldset"><legend><label><input type="checkbox" checked={value.stroke_enabled} onChange={(event) => onChange({ stroke_enabled: event.target.checked })}/> Stroke</label></legend><div className="custom-text-control-grid"><label>Width <strong>{value.stroke_width.toFixed(1)} px</strong><input type="range" min="0" max="20" step="0.5" value={value.stroke_width} onChange={(event) => onChange({ stroke_width: Number(event.target.value) })}/></label><label>Color<input type="color" value={value.stroke_color} onChange={(event) => onChange({ stroke_color: event.target.value })}/></label></div></fieldset>
    <fieldset className="custom-effect-fieldset"><legend><label><input type="checkbox" checked={value.shadow_enabled} onChange={(event) => onChange({ shadow_enabled: event.target.checked })}/> Shadow</label></legend><div className="custom-text-control-grid"><label>Blur <strong>{value.shadow_blur.toFixed(1)} px</strong><input type="range" min="0" max="40" step="0.5" value={value.shadow_blur} onChange={(event) => onChange({ shadow_blur: Number(event.target.value) })}/></label><label>Color<input type="color" value={value.shadow_color} onChange={(event) => onChange({ shadow_color: event.target.value })}/></label><label>Horizontal offset <strong>{value.shadow_x.toFixed(0)} px</strong><input type="range" min="-30" max="30" value={value.shadow_x} onChange={(event) => onChange({ shadow_x: Number(event.target.value) })}/></label><label>Vertical offset <strong>{value.shadow_y.toFixed(0)} px</strong><input type="range" min="-30" max="30" value={value.shadow_y} onChange={(event) => onChange({ shadow_y: Number(event.target.value) })}/></label></div></fieldset>
    <button type="button" className="button secondary small" onClick={() => onChange(preferredEffects)}><RotateCcw size={13}/> Reset stroke & shadow</button>
  </div>
}
