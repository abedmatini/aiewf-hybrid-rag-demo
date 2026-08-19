/**
 * Tests 7.1–7.8: ChatMessages component
 *
 * Covers the consent gate (null / declined states) and the live message list.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, afterEach } from 'vitest'
import ChatMessages from '../components/ChatMessages'

const noop = () => {}

afterEach(() => {
  vi.unstubAllGlobals()
})

// ---------------------------------------------------------------------------
// 7.1 – 7.5  Consent gate
// ---------------------------------------------------------------------------

describe('ChatMessages – Consent gate', () => {
  it('7.1 renders consent card when consent is not accepted', () => {
    render(<ChatMessages messages={[]} consent={null} onConsent={noop} />)
    expect(screen.getByRole('button', { name: /I understand/i })).toBeInTheDocument()
  })

  it('7.2 accept button receives focus on mount (consent=null)', () => {
    // Stub rAF to fire the callback synchronously so the focus happens inside act()
    vi.stubGlobal('requestAnimationFrame', (cb) => { cb(); return 0 })
    render(<ChatMessages messages={[]} consent={null} onConsent={noop} />)
    const btn = screen.getByRole('button', { name: /I understand/i })
    expect(document.activeElement).toBe(btn)
  })

  it('7.3 clicking accept calls onConsent(true)', async () => {
    const user = userEvent.setup()
    const onConsent = vi.fn()
    render(<ChatMessages messages={[]} consent={null} onConsent={onConsent} />)
    await user.click(screen.getByRole('button', { name: /I understand/i }))
    expect(onConsent).toHaveBeenCalledOnce()
    expect(onConsent).toHaveBeenCalledWith(true)
  })

  it('7.4 clicking "No thanks" calls onConsent(false)', async () => {
    const user = userEvent.setup()
    const onConsent = vi.fn()
    render(<ChatMessages messages={[]} consent={null} onConsent={onConsent} />)
    await user.click(screen.getByText(/No thanks/i))
    expect(onConsent).toHaveBeenCalledOnce()
    expect(onConsent).toHaveBeenCalledWith(false)
  })

  it('7.5 declined state renders "Chat is unavailable" — buttons absent', () => {
    render(<ChatMessages messages={[]} consent="declined" onConsent={noop} />)
    expect(screen.getByText(/Chat is unavailable/i)).toBeInTheDocument()
    expect(screen.queryByText(/I understand/i)).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// 7.6 – 7.8  Message list
// ---------------------------------------------------------------------------

describe('ChatMessages – Message list', () => {
  const messages = [
    { role: 'user', content: 'Hello' },
    { role: 'assistant', content: 'Hi there' },
  ]

  it('7.6 messages container has role="log" and aria-live="polite"', () => {
    render(<ChatMessages messages={messages} consent="accepted" onConsent={noop} />)
    const log = screen.getByRole('log')
    expect(log).toHaveAttribute('aria-live', 'polite')
  })

  // FINDING: message bubbles do not currently have role="article"
  it.fails('7.7 bot messages have role="article" (FINDING: ARIA role missing)', () => {
    render(
      <ChatMessages
        messages={[{ role: 'assistant', content: 'Hello' }]}
        consent="accepted"
        onConsent={noop}
      />
    )
    expect(screen.getAllByRole('article')).toHaveLength(1)
  })

  it('7.8 escalation message renders the escalation badge', () => {
    const msgs = [{ role: 'assistant', content: 'See your HCP', escalation: true }]
    render(<ChatMessages messages={msgs} consent="accepted" onConsent={noop} />)
    expect(screen.getByText(/Medical escalation/i)).toBeInTheDocument()
  })
})
