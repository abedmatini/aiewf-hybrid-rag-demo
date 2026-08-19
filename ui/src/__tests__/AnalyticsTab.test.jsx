/**
 * Tests 7.20–7.25: AnalyticsTab component
 *
 * The component fetches from GET /analytics/summary on mount.  All tests mock
 * global fetch; a shared helper builds the mock response.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, afterEach } from 'vitest'
import AnalyticsTab from '../components/admin/AnalyticsTab'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeFetch(data) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(data),
  })
}

const BASE_DATA = {
  total_chats: 42,
  escalation_count: 5,
  escalation_rate: 12,
  no_match_count: 3,
  avg_duration_ms: 1500,
  top_questions: [{ message: 'What is vitamin D?', count: 10 }],
  recent_logs: [],
}

afterEach(() => {
  vi.unstubAllGlobals()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AnalyticsTab – loading state', () => {
  it('7.20 shows loading indicator on mount before fetch resolves', () => {
    // Return a permanently-pending promise so the component stays in loading state
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    render(<AnalyticsTab />)
    expect(screen.getByText(/Loading analytics/i)).toBeInTheDocument()
  })
})

describe('AnalyticsTab – data display', () => {
  it('7.21 renders 4 summary cards when data arrives', async () => {
    vi.stubGlobal('fetch', makeFetch(BASE_DATA))
    render(<AnalyticsTab />)
    await waitFor(() => screen.getByText('Total chats'))
    expect(screen.getAllByText(/last 30 days|escalated|gaps in knowledge|end-to-end/i)).toHaveLength(4)
  })

  it('7.22 escalation rate card gets amber class when rate > 20 %', async () => {
    vi.stubGlobal('fetch', makeFetch({ ...BASE_DATA, escalation_rate: 25 }))
    render(<AnalyticsTab />)
    await waitFor(() => screen.getByText('Escalation rate'))
    const card = screen.getByText('Escalation rate').parentElement
    expect(card).toHaveClass('analytics-card--warn')
  })

  it('7.23 escalation rate card has no amber class when rate ≤ 20 %', async () => {
    vi.stubGlobal('fetch', makeFetch({ ...BASE_DATA, escalation_rate: 15 }))
    render(<AnalyticsTab />)
    await waitFor(() => screen.getByText('Escalation rate'))
    const card = screen.getByText('Escalation rate').parentElement
    expect(card).not.toHaveClass('analytics-card--warn')
  })

  it('7.24 clicking Refresh re-fetches data (fetch called twice)', async () => {
    const user = userEvent.setup()
    const mockFetch = makeFetch(BASE_DATA)
    vi.stubGlobal('fetch', mockFetch)

    render(<AnalyticsTab />)
    await waitFor(() => screen.getByText('Total chats'))

    await user.click(screen.getByRole('button', { name: /Refresh/i }))
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2))
  })

  it('7.25 renders "No data yet" when top_questions is empty', async () => {
    vi.stubGlobal('fetch', makeFetch({ ...BASE_DATA, top_questions: [] }))
    render(<AnalyticsTab />)
    await waitFor(() => screen.getByText(/No data yet/i))
    expect(screen.getByText(/No data yet/i)).toBeInTheDocument()
  })
})
