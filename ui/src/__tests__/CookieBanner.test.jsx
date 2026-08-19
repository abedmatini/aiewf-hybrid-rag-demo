/**
 * Tests 7.15–7.19: CookieBanner component
 *
 * GA_ENABLED is a compile-time constant in analytics.js.  We use vi.hoisted()
 * to create a mutable state object that the mock factory can close over safely,
 * then toggle it per-test so we can cover both the enabled and disabled paths.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ---------------------------------------------------------------------------
// Mutable GA flag shared between the mock factory and the tests.
// vi.hoisted() ensures it is available before vi.mock() is evaluated.
// ---------------------------------------------------------------------------
const gaState = vi.hoisted(() => ({ enabled: false }))

vi.mock('../analytics.js', () => ({
  get GA_ENABLED() { return gaState.enabled },
  initGA: vi.fn(),
}))

// Import AFTER the mock is declared so it picks up the mocked module.
import CookieBanner from '../components/CookieBanner'

const STORAGE_KEY = 'faq_cookies'

beforeEach(() => {
  localStorage.clear()
  gaState.enabled = false
})

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('CookieBanner – visibility rules', () => {
  it('7.15 is not rendered when GA_ENABLED is false', () => {
    gaState.enabled = false
    const { container } = render(<CookieBanner />)
    expect(container.firstChild).toBeNull()
  })

  it('7.16 is not rendered when faq_cookies is already set in localStorage', () => {
    gaState.enabled = true
    localStorage.setItem(STORAGE_KEY, 'accepted')
    const { container } = render(<CookieBanner />)
    expect(container.firstChild).toBeNull()
  })
})

describe('CookieBanner – user interactions (GA enabled)', () => {
  beforeEach(() => {
    gaState.enabled = true
  })

  it('7.17 clicking "Accept cookies" stores "accepted" in localStorage', async () => {
    const user = userEvent.setup()
    render(<CookieBanner />)
    await user.click(screen.getByText(/Accept cookies/i))
    expect(localStorage.getItem(STORAGE_KEY)).toBe('accepted')
  })

  it('7.18 clicking "Decline" stores "declined" in localStorage', async () => {
    const user = userEvent.setup()
    render(<CookieBanner />)
    await user.click(screen.getByText(/^Decline$/i))
    expect(localStorage.getItem(STORAGE_KEY)).toBe('declined')
  })

  it('7.19 privacy policy link is hidden when VITE_PRIVACY_POLICY_URL is unset', () => {
    // .env sets VITE_PRIVACY_POLICY_URL; override it to empty for this test
    vi.stubEnv('VITE_PRIVACY_POLICY_URL', '')
    render(<CookieBanner />)
    expect(screen.queryByRole('link', { name: /Privacy/i })).not.toBeInTheDocument()
  })
})
