/**
 * Tests 7.9–7.14: ChatInput component
 *
 * Covers send-button disabled states, keyboard behaviour (Enter / Shift+Enter),
 * and accessibility attributes.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import ChatInput from '../components/ChatInput'

describe('ChatInput – Send button state', () => {
  it('7.9 send button is disabled when textarea is empty', () => {
    render(<ChatInput onSend={() => {}} />)
    expect(screen.getByRole('button', { name: /Send message/i })).toBeDisabled()
  })

  it('7.10 send button is enabled after typing text', async () => {
    const user = userEvent.setup()
    render(<ChatInput onSend={() => {}} />)
    await user.type(screen.getByRole('textbox'), 'Hello')
    expect(screen.getByRole('button', { name: /Send message/i })).not.toBeDisabled()
  })

  it('7.11 send button stays disabled when disabled prop is true (even with text)', async () => {
    const user = userEvent.setup()
    render(<ChatInput onSend={() => {}} disabled={true} />)
    // typing into a disabled textarea should be a no-op, but we verify the button state
    await user.type(screen.getByRole('textbox'), 'Hello', { skipClick: true })
    expect(screen.getByRole('button', { name: /Send message/i })).toBeDisabled()
  })
})

describe('ChatInput – Keyboard behaviour', () => {
  it('7.12 Enter key fires onSend with trimmed text', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()
    render(<ChatInput onSend={onSend} />)
    await user.type(screen.getByRole('textbox'), 'Hello world')
    await user.keyboard('{Enter}')
    expect(onSend).toHaveBeenCalledOnce()
    expect(onSend).toHaveBeenCalledWith('Hello world')
  })

  it('7.13 Shift+Enter does NOT fire onSend', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()
    render(<ChatInput onSend={onSend} />)
    await user.type(screen.getByRole('textbox'), 'Hello')
    await user.keyboard('{Shift>}{Enter}{/Shift}')
    expect(onSend).not.toHaveBeenCalled()
  })
})

describe('ChatInput – Accessibility', () => {
  it('7.14 textarea has aria-label "Type your message"', () => {
    render(<ChatInput onSend={() => {}} />)
    expect(screen.getByLabelText('Type your message')).toBeInTheDocument()
  })
})
