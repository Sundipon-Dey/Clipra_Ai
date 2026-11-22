import { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import CaptionOverlay from './CaptionOverlay'
import CustomTextOverlay from './CustomTextOverlay'
import './styles.css'
import type { CaptionTrack, CustomText } from './api'

type RenderPayload = { track: CaptionTrack | null; customText: CustomText | null; clipStartSeconds: number }

declare global {
  interface Window {
    __clipraRenderPayload: RenderPayload
    clipraSetCaptionTime?: (sourceTime: number) => Promise<void>
  }
}

function CaptionRenderer() {
  const payload = window.__clipraRenderPayload
  const [currentSourceTime, setCurrentSourceTime] = useState(payload.clipStartSeconds - 1)

  useEffect(() => {
    window.clipraSetCaptionTime = async (sourceTime) => {
      setCurrentSourceTime(sourceTime)
      await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))

      const relative = sourceTime - payload.clipStartSeconds + (payload.track?.timing_offset_seconds ?? 0)
      if (payload.track) {
        const segment = payload.track.segments.find((item) => relative >= item.start_seconds && relative < item.end_seconds)
        const activeWord = segment?.words.find((word) => relative >= word.start_seconds && relative < word.end_seconds)
        const caption = document.querySelector<HTMLElement>('.caption-overlay:not(.custom-text-overlay) .caption-text')
        if (caption && segment) {
          const oneWordMode = payload.track.grouping.display_mode === 'one_word'
          const captionStart = oneWordMode && activeWord ? activeWord.start_seconds : segment.start_seconds
          const captionTime = Math.max(0, (relative - captionStart) * 1000)
          for (const animation of caption.getAnimations()) {
            animation.pause()
            animation.currentTime = captionTime
          }
          if (activeWord) {
            const wordTime = Math.max(0, (relative - activeWord.start_seconds) * 1000)
            for (const word of caption.querySelectorAll<HTMLElement>('.active-word-pop')) {
              for (const animation of word.getAnimations()) { animation.pause(); animation.currentTime = wordTime }
            }
          }
        }
      }
      const custom = document.querySelector<HTMLElement>('.custom-text-content')
      if (custom) for (const animation of custom.getAnimations()) {
        animation.pause()
        animation.currentTime = Math.max(0, sourceTime - payload.clipStartSeconds) * 1000
      }
    }
    return () => { delete window.clipraSetCaptionTime }
  }, [payload])

  return <><CaptionOverlay track={payload.track} clipStart={payload.clipStartSeconds} currentSourceTime={currentSourceTime} editing={false} onPosition={() => undefined}/>{payload.customText && <CustomTextOverlay value={payload.customText} clipStart={payload.clipStartSeconds} currentSourceTime={currentSourceTime}/>}</>
}

ReactDOM.createRoot(document.getElementById('root')!).render(<CaptionRenderer />)
