import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SocialContentPanel from './SocialContentPanel'
import type { SocialContentGeneration } from './api'

const { getSocialContentHistory, startSocialContentGeneration, saveSocialPackage } = vi.hoisted(() => ({
  getSocialContentHistory: vi.fn(), startSocialContentGeneration: vi.fn(), saveSocialPackage: vi.fn(),
}))
vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()), getSocialContentHistory, startSocialContentGeneration, saveSocialPackage,
}))

const short = { caption: 'Generated caption', opening_hook: 'Hook', hashtags: ['#clip'], suggested_keywords: ['gameplay'], alternate_caption: 'Alternate' }
const packages = { tiktok: short, instagram_reels: short, facebook_reels: short, youtube_shorts: { title: 'Title', description: 'Description', hashtags: ['#shorts'], tags: ['game'], alternate_title: 'Other title' } }
const completed: SocialContentGeneration = { id: 'generation-1', render_job_id: 'export-1', status: 'completed', progress: 1, stage: 'completed', model_name: 'gemini-configured', prompt_version: 'stage6-social-v1', error_code: null, error_message: null, cleanup_pending: false, created_at: '2026-11-22T00:00:00Z', completed_at: '2026-11-22T00:00:01Z', generated_packages: packages, packages }

describe('SocialContentPanel', () => {
  beforeEach(() => { vi.clearAllMocks(); getSocialContentHistory.mockResolvedValue([]) })

  it('requires fresh consent before starting each generation', async () => {
    startSocialContentGeneration.mockResolvedValue({ ...completed, status: 'queued', packages: null, generated_packages: null })
    render(<SocialContentPanel renderJobId="export-1" version={2}/>)
    const generate = screen.getByRole('button', { name: /generate social content/i })
    expect(generate).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox'))
    expect(generate).toBeEnabled()
    fireEvent.click(generate)
    await waitFor(() => expect(startSocialContentGeneration).toHaveBeenCalledWith('export-1'))
    expect(screen.getByRole('checkbox')).not.toBeChecked()
  })

  it('shows platform-specific text and saves user edits', async () => {
    getSocialContentHistory.mockResolvedValue([completed])
    saveSocialPackage.mockResolvedValue({ ...completed, packages: { ...packages, tiktok: { ...short, caption: 'Edited by me' } } })
    render(<SocialContentPanel renderJobId="export-1" version={1}/>)
    const caption = await screen.findByLabelText('Caption')
    await waitFor(() => expect(caption).toHaveValue('Generated caption'))
    fireEvent.change(caption, { target: { value: 'Edited by me' } })
    expect(screen.getByRole('button', { name: /generate new version/i })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: /save this platform/i }))
    await waitFor(() => expect(saveSocialPackage).toHaveBeenCalledWith('generation-1', 'tiktok', expect.objectContaining({ caption: 'Edited by me' })))
    expect(await screen.findByText(/changes saved/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'YouTube Shorts' }))
    expect(await screen.findByLabelText('SEO title')).toHaveValue('Title')
  })
})
