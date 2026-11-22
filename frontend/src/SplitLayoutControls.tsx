import { useState, type ChangeEvent } from 'react'
import { ImagePlus, LoaderCircle } from 'lucide-react'
import { uploadLayoutImage, type LayoutImage, type SplitLayout } from './api'
import { clampSplitRatio, type SplitSectionKey } from './splitLayout'

type Props = { clipId: string; value: SplitLayout; active: SplitSectionKey; onActive: (key: SplitSectionKey) => void; onChange: (next: SplitLayout) => void; onImageUploaded: (image: LayoutImage, section: SplitSectionKey) => void }

export default function SplitLayoutControls({ clipId, value, active, onActive, onChange, onImageUploaded }: Props) {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const section = value[active]
  const sectionName = active === 'top' ? 'Top' : 'Bottom'
  const sourceMode = section.source_mode ?? 'same_video'
  const updateSection = (fields: Record<string, unknown>) => onChange(active === 'top'
    ? { ...value, top: { ...value.top, ...fields } }
    : { ...value, bottom: { ...value.bottom, ...fields } })
  const onFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    setUploading(true); setError('')
    try {
      const image = await uploadLayoutImage(clipId, file)
      onImageUploaded(image, active)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The custom image could not be uploaded.')
    } finally { setUploading(false); event.target.value = '' }
  }
  return <div className="split-layout-controls">
    <div className="split-section-tabs" role="tablist" aria-label="Section controls">
      <button type="button" role="tab" aria-selected={active === 'top'} className={active === 'top' ? 'active' : ''} onClick={() => onActive('top')}>Top</button>
      <button type="button" role="tab" aria-selected={active === 'bottom'} className={active === 'bottom' ? 'active' : ''} onClick={() => onActive('bottom')}>Bottom</button>
    </div>
    <label className="editor-field slider-field">Top section size <strong>{Math.round(value.split_ratio * 100)}%</strong>
      <input aria-label="Top section size" type="range" min="0.25" max="0.75" step="0.01" value={value.split_ratio} onChange={(event) => onChange({ ...value, split_ratio: clampSplitRatio(Number(event.target.value)) })}/>
    </label>
    <div className="editor-field">{sectionName} source
      <div className="framing-options split-source-options">
        <button type="button" className={sourceMode === 'same_video' ? 'framing-option active' : 'framing-option'} onClick={() => updateSection({ source_mode: 'same_video' })}>Same Video</button>
        <button type="button" className={sourceMode === 'custom_image' ? 'framing-option active' : 'framing-option'} onClick={() => updateSection({ source_mode: 'custom_image' })}>Custom Image</button>
        <button type="button" className={sourceMode === 'solid_color' ? 'framing-option active' : 'framing-option'} onClick={() => updateSection({ source_mode: 'solid_color' })}>Solid Color</button>
      </div>
      {sourceMode === 'solid_color' && <label className="editor-field">{sectionName} panel color<input aria-label={`${sectionName} solid color`} type="color" value={section.solid_color ?? '#151923'} onChange={(event) => updateSection({ solid_color: event.target.value })}/></label>}
      {sourceMode === 'custom_image' && <div className="split-image-upload">
        <label className="button secondary small"><ImagePlus size={14}/>{uploading ? 'Validating image…' : 'Choose PNG, JPG or WebP'}<input aria-label={`Choose custom ${active} image`} type="file" accept="image/png,image/jpeg,image/webp" disabled={uploading} onChange={onFile} hidden/></label>
        {uploading && <LoaderCircle className="spin" size={15}/>}
        {section.image_asset_id && <small>Saved image selected. It remains in project storage while layouts and render snapshots may reference it.</small>}
        {error && <small role="alert" className="framing-error">{error}</small>}
      </div>}
    </div>
    {sourceMode !== 'solid_color' && <><label className="editor-field">{sectionName} framing
      <select aria-label={`${active === 'top' ? 'Top' : 'Bottom'} framing`} value={section.framing_mode} onChange={(event) => updateSection({ framing_mode: event.target.value })}>
        <option value="crop">Crop to fill</option><option value="fit">Fit inside section</option>
      </select>
    </label>
    <label className="editor-field slider-field">{active === 'top' ? 'Top zoom' : 'Bottom zoom'} <strong>{section.zoom.toFixed(2)}×</strong>
      <input aria-label={`${sectionName} zoom`} type="range" min="1" max="10" step="0.01" value={section.zoom} onChange={(event) => updateSection({ zoom: Number(event.target.value) })}/>
    </label>
    <label className="editor-field slider-field">Trim top and bottom <strong>{(section.vertical_crop_percent ?? 0).toFixed(1)}% each</strong>
      <input aria-label={`${sectionName} vertical trim`} type="range" min="0" max="40" step="0.5" value={section.vertical_crop_percent ?? 0} onChange={(event) => updateSection({ vertical_crop_percent: Number(event.target.value) })}/>
    </label>
    <div className="focus-coordinates"><label>{sectionName} X / focus <input aria-label={`${sectionName} horizontal position`} type="number" min="0" max="1" step="0.01" value={section.position_x.toFixed(2)} onChange={(event) => updateSection({ position_x: Number(event.target.value) })}/></label><label>{sectionName} Y / focus <input aria-label={`${sectionName} vertical position`} type="number" min="0" max="1" step="0.01" value={section.position_y.toFixed(2)} onChange={(event) => updateSection({ position_y: Number(event.target.value) })}/></label></div>
    {section.framing_mode === 'fit' && <label className="editor-field">Section background<input aria-label={`${active} fit background color`} type="color" value={section.fit_background_color} onChange={(event) => updateSection({ fit_background_color: event.target.value })}/></label>}</>}
    <p className="framing-help">{sourceMode === 'solid_color' ? `The solid color fills the ${active} section.` : 'Drag inside either preview section to reposition its content. Top and bottom settings are saved independently.'}</p>
  </div>
}
