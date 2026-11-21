import { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import CaptionOverlay from './CaptionOverlay'
import './styles.css'
import type { CaptionTrack } from './api'

type RenderPayload = { track: CaptionTrack; clipStartSeconds: number }

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

      const relative = sourceTime - payload.clipStartSeconds + payload.track.timing_offset_seconds
      const segment = payload.track.segments.find((item) => relative >= item.start_seconds && relative < item.end_seconds)
      const activeWord = segment?.words.find((word) => relative >= word.start_seconds && relative < word.end_seconds)
      const caption = document.querySelector<HTMLElement>('.caption-text')
      if (!caption || !segment) return

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
          for (const animation of word.getAnimations()) {
            animation.pause()
            animation.currentTime = wordTime
          }
        }
      }
    }
    return () => { delete window.clipraSetCaptionTime }
  }, [payload])

  return <CaptionOverlay track={payload.track} clipStart={payload.clipStartSeconds} currentSourceTime={currentSourceTime} editing={false} onPosition={() => undefined}/>
}

ReactDOM.createRoot(document.getElementById('root')!).render(<CaptionRenderer />)
