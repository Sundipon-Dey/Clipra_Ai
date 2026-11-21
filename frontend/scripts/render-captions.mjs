import { createServer } from 'vite'
import { chromium } from 'playwright-core'
import { copyFile, link, mkdir, readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function writeProgress(frame, total) {
  process.stdout.write(`${JSON.stringify({ frame, total })}\n`)
}

async function linkOrCopy(source, target) {
  try {
    await link(source, target)
  } catch {
    await copyFile(source, target)
  }
}

function frameCaptionState(track, clipStartSeconds, sourceTime) {
  const relative = sourceTime - clipStartSeconds + track.timing_offset_seconds
  const segment = track.segments.find((item) => relative >= item.start_seconds && relative < item.end_seconds)
  const word = segment?.words.find((item) => relative >= item.start_seconds && relative < item.end_seconds)
  if (!segment || (track.grouping.display_mode === 'one_word' && !word)) return { key: 'blank' }

  const style = track.style
  const oneWord = track.grouping.display_mode === 'one_word'
  const rootAnimation = style.animation === 'fade' || (!oneWord && ['pop', 'pop_karaoke'].includes(style.animation))
  const captionStart = oneWord && word ? word.start_seconds : segment.start_seconds
  const captionElapsed = Math.max(0, relative - captionStart)
  const wordElapsed = word ? Math.max(0, relative - word.start_seconds) : 0
  const captionDuration = style.animation_ms || 140
  const wordDuration = style.animation_ms || 120
  const captionPhase = rootAnimation && captionElapsed * 1000 < captionDuration
    ? Math.floor(captionElapsed * 1000)
    : 'settled'
  const wordPhase = word && wordElapsed * 1000 < wordDuration
    ? Math.floor(wordElapsed * 1000)
    : 'settled'

  return { key: `${segment.id}|${word?.id ?? 'none'}|${captionPhase}|${wordPhase}` }
}

async function main() {
  const requestPath = process.argv[2]
  if (!requestPath) throw new Error('Caption render request path is required.')
  const request = JSON.parse(await readFile(requestPath, 'utf8'))
  const { track, clipStartSeconds, durationSeconds, fps, frameCount, framesDirectory } = request
  if (!track || !Array.isArray(track.segments) || !Number.isFinite(clipStartSeconds) || !Number.isFinite(durationSeconds) || !Number.isFinite(fps) || !Number.isInteger(frameCount) || frameCount < 1) {
    throw new Error('Caption render request is invalid.')
  }
  const frameDirectory = resolve(framesDirectory)
  await mkdir(frameDirectory, { recursive: true })

  const server = await createServer({
    configFile: resolve(frontendRoot, 'vite.config.ts'),
    root: frontendRoot,
    logLevel: 'error',
    server: { host: '127.0.0.1', port: 0, strictPort: false, hmr: false },
  })
  let browser
  try {
    await server.listen()
    const address = server.httpServer.address()
    if (!address || typeof address === 'string') throw new Error('Caption renderer could not bind its local page server.')

    const errors = []
    for (const channel of ['msedge', 'chrome']) {
      try {
        browser = await chromium.launch({
          channel,
          headless: true,
          args: ['--disable-background-networking', '--disable-component-update', '--no-first-run', '--disable-features=TranslateUI', '--hide-scrollbars'],
        })
        break
      } catch (error) {
        errors.push(`${channel}: ${error instanceof Error ? error.message : String(error)}`)
      }
    }
    if (!browser) throw new Error(`CLIPRA needs Microsoft Edge or Google Chrome installed for caption rendering. ${errors.join(' | ')}`)

    const context = await browser.newContext({ viewport: { width: 360, height: 640 }, deviceScaleFactor: 3, reducedMotion: 'no-preference', colorScheme: 'dark' })
    const page = await context.newPage()
    page.setDefaultTimeout(30_000)
    const payload = { track, clipStartSeconds }
    await page.addInitScript((initial) => { window.__clipraRenderPayload = initial }, payload)
    await page.goto(`http://127.0.0.1:${address.port}/caption-renderer.html`, { waitUntil: 'networkidle' })
    await page.evaluate(() => {
      document.documentElement.style.setProperty('background', 'transparent', 'important')
      document.body.style.setProperty('background', 'transparent', 'important')
      document.getElementById('root')?.style.setProperty('background', 'transparent', 'important')
    })
    await page.evaluate(() => document.fonts.ready)
    await page.waitForFunction(() => typeof window.clipraSetCaptionTime === 'function')

    const blankPath = resolve(frameDirectory, 'blank.png')
    await page.evaluate((time) => window.clipraSetCaptionTime?.(time), clipStartSeconds - 1)
    await page.screenshot({ path: blankPath, omitBackground: true, scale: 'device', animations: 'allow' })

    const stateImages = new Map([['blank', blankPath]])
    for (let frame = 0; frame < frameCount; frame++) {
      const seconds = frame / fps
      const sourceTime = clipStartSeconds + seconds
      const { key } = frameCaptionState(track, clipStartSeconds, sourceTime)
      let imagePath = stateImages.get(key)
      if (!imagePath) {
        await page.evaluate((time) => window.clipraSetCaptionTime?.(time), sourceTime)
        imagePath = resolve(frameDirectory, `state-${String(stateImages.size).padStart(6, '0')}.png`)
        await page.screenshot({ path: imagePath, omitBackground: true, scale: 'device', animations: 'allow' })
        stateImages.set(key, imagePath)
      }

      const framePath = resolve(frameDirectory, `frame-${String(frame).padStart(8, '0')}.png`)
      await linkOrCopy(imagePath, framePath)
      if ((frame + 1) % Math.max(1, Math.floor(fps)) === 0 || frame + 1 === frameCount) writeProgress(frame + 1, frameCount)
    }
    await context.close()
  } finally {
    if (browser) await browser.close()
    await server.close()
  }
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack ?? error.message : String(error)}\n`)
  process.exitCode = 1
})
