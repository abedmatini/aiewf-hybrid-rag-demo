/**
 * Tests 7.28–7.47: ChatPage agent mode badge + SettingsTab agent controls
 *
 * 7.28–7.32  Agent mode badge in ChatPage
 * 7.33–7.39  Tool step cards rendered in ChatMessages
 * 7.40–7.47  SettingsTab agent controls (agent_mode toggle, agent_model, tools grid)
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import ChatPage from '../pages/ChatPage'
import ChatMessages from '../components/ChatMessages'
import SettingsTab from '../components/admin/SettingsTab'
import { MemoryRouter } from 'react-router-dom'

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

/** Stub fetch so the component doesn't actually call the API. */
function stubFetch(overrides = {}) {
  const defaults = {
    settings: {
      chat_model: 'gemma4:latest', top_k: 5,
      system_prompt: 'You are helpful.',
      escalation_message: 'See your HCP.',
      agent_mode: true, agent_model: 'qwen2.5:7b-instruct',
    },
    models: { models: ['qwen2.5:7b-instruct', 'llama3:8b'] },
    agents: {
      tools: [
        { name: 'search_kb', description: 'Search the KB' },
        { name: 'list_products', description: 'List products' },
        { name: 'get_product_info', description: 'Get info' },
        { name: 'compare_products', description: 'Compare' },
        { name: 'get_current_date', description: 'Get date' },
        { name: 'calculate', description: 'Calculate' },
      ],
    },
    suggestions: { suggestions: [] },
    ...overrides,
  }

  vi.stubGlobal('fetch', vi.fn((url) => {
    let data
    if (url.includes('/settings/agents')) data = defaults.agents
    else if (url.includes('/settings'))   data = defaults.settings
    else if (url.includes('/models'))     data = defaults.models
    else if (url.includes('/suggestions')) data = defaults.suggestions
    else data = {}
    return Promise.resolve({ ok: true, json: () => Promise.resolve(data) })
  }))
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// 7.28–7.32  Agent mode badge in ChatPage
// ---------------------------------------------------------------------------

describe('ChatPage – agent mode badge', () => {
  it('7.28 badge renders when agentMode loads as true', async () => {
    stubFetch()
    render(<MemoryRouter><ChatPage /></MemoryRouter>)
    await waitFor(() =>
      expect(screen.getByText(/Agent mode/i)).toBeInTheDocument()
    )
    expect(document.querySelector('.chat-agent-badge')).toBeTruthy()
  })

  it('7.29 badge absent when settings return agent_mode: false', async () => {
    stubFetch({ settings: {
      chat_model: 'gemma4:latest', top_k: 5,
      system_prompt: '', escalation_message: '',
      agent_mode: false, agent_model: 'qwen2.5:7b-instruct',
    }})
    render(<MemoryRouter><ChatPage /></MemoryRouter>)
    // Wait for the fetch to resolve, then confirm badge is absent
    await waitFor(() => {})  // let effects settle
    await new Promise(r => setTimeout(r, 50))
    expect(document.querySelector('.chat-agent-badge')).toBeFalsy()
  })

  it('7.30 badge shows model name when agentModel is set', async () => {
    stubFetch()
    render(<MemoryRouter><ChatPage /></MemoryRouter>)
    await waitFor(() =>
      expect(screen.getByText('qwen2.5:7b-instruct')).toBeInTheDocument()
    )
  })

  it('7.31 badge shows no model chip when agentModel is empty', async () => {
    stubFetch({ settings: {
      chat_model: 'gemma4:latest', top_k: 5,
      system_prompt: '', escalation_message: '',
      agent_mode: true, agent_model: '',
    }})
    render(<MemoryRouter><ChatPage /></MemoryRouter>)
    await waitFor(() =>
      expect(screen.getByText(/Agent mode/i)).toBeInTheDocument()
    )
    expect(document.querySelector('.chat-agent-badge__model')).toBeFalsy()
  })

  it('7.32 pulsing dot element present when badge is visible', async () => {
    stubFetch()
    render(<MemoryRouter><ChatPage /></MemoryRouter>)
    await waitFor(() =>
      expect(document.querySelector('.chat-agent-badge')).toBeTruthy()
    )
    expect(document.querySelector('.chat-agent-badge__dot')).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// 7.33–7.39  Tool step cards in ChatMessages
// ---------------------------------------------------------------------------

const TOOL_STEP_RUNNING = [{ name: 'search_kb', args: { query: 'vitamin D' }, result: null }]
const TOOL_STEP_DONE    = [{ name: 'search_kb', args: { query: 'vitamin D' }, result: 'Found 2 chunks.' }]
const TWO_STEPS         = [
  { name: 'search_kb', args: { query: 'tylenol' }, result: 'Result A' },
  { name: 'calculate', args: { expression: '2+2' }, result: '4' },
]

describe('ChatMessages – tool step cards', () => {
  it('7.33 running tool step shows ⟳ icon and running class', () => {
    const msg = { role: 'assistant', content: '', pending: true, toolSteps: TOOL_STEP_RUNNING }
    render(<ChatMessages messages={[msg]} consent="accepted" onConsent={() => {}} />)
    expect(document.querySelector('.tool-step--running')).toBeTruthy()
    expect(screen.getByText('⟳')).toBeInTheDocument()
  })

  it('7.34 done tool step shows ✓ icon and done class', () => {
    const msg = { role: 'assistant', content: '', pending: false, toolSteps: TOOL_STEP_DONE }
    render(<ChatMessages messages={[msg]} consent="accepted" onConsent={() => {}} />)
    expect(document.querySelector('.tool-step--done')).toBeTruthy()
    expect(screen.getByText('✓')).toBeInTheDocument()
  })

  it('7.35 clicking done step header expands result text', async () => {
    const user = userEvent.setup()
    const msg = { role: 'assistant', content: '', pending: false, toolSteps: TOOL_STEP_DONE }
    render(<ChatMessages messages={[msg]} consent="accepted" onConsent={() => {}} />)

    // result is hidden until header is clicked
    expect(screen.queryByText('Found 2 chunks.')).not.toBeInTheDocument()
    await user.click(document.querySelector('.tool-step__header'))
    expect(screen.getByText('Found 2 chunks.')).toBeInTheDocument()
  })

  it('7.36 two tool_call steps render two separate tool-step cards', () => {
    const msg = { role: 'assistant', content: '', pending: false, toolSteps: TWO_STEPS }
    render(<ChatMessages messages={[msg]} consent="accepted" onConsent={() => {}} />)
    const cards = document.querySelectorAll('.tool-step')
    expect(cards.length).toBe(2)
  })

  it('7.37 tool step shows friendly label from TOOL_LABELS map', () => {
    const msg = { role: 'assistant', content: '', pending: false, toolSteps: TOOL_STEP_DONE }
    render(<ChatMessages messages={[msg]} consent="accepted" onConsent={() => {}} />)
    expect(screen.getByText('🔍 Search KB')).toBeInTheDocument()
  })

  it('7.38 query arg shown inside step header when present', () => {
    const msg = { role: 'assistant', content: '', pending: true, toolSteps: TOOL_STEP_RUNNING }
    render(<ChatMessages messages={[msg]} consent="accepted" onConsent={() => {}} />)
    expect(screen.getByText(/"vitamin D"/i)).toBeInTheDocument()
  })

  it('7.39 tool steps absent on new empty pending message (previous turn cleared)', () => {
    // New turn: pending assistant message with no toolSteps yet
    const msg = { role: 'assistant', content: '', pending: true }
    render(<ChatMessages messages={[msg]} consent="accepted" onConsent={() => {}} />)
    expect(document.querySelector('.tool-steps')).toBeFalsy()
  })
})

// ---------------------------------------------------------------------------
// 7.40–7.47  SettingsTab agent controls
// ---------------------------------------------------------------------------

describe('SettingsTab – agent controls', () => {
  beforeEach(() => stubFetch())

  it('7.40 "Agent mode" heading is visible in Settings tab', async () => {
    render(<SettingsTab />)
    await waitFor(() => expect(screen.getByText('Agent mode')).toBeInTheDocument())
  })

  it('7.41 agent mode toggle button has role="switch"', async () => {
    render(<SettingsTab />)
    await waitFor(() => {
      const toggle = screen.getByRole('switch')
      expect(toggle).toBeInTheDocument()
    })
  })

  it('7.42 toggle aria-pressed reflects agent_mode from settings', async () => {
    render(<SettingsTab />)
    await waitFor(() => {
      const toggle = screen.getByRole('switch')
      expect(toggle).toHaveAttribute('aria-pressed', 'true')
    })
  })

  it('7.43 clicking toggle flips aria-pressed to false', async () => {
    const user = userEvent.setup()
    render(<SettingsTab />)
    await waitFor(() => screen.getByRole('switch'))
    await user.click(screen.getByRole('switch'))
    expect(screen.getByRole('switch')).toHaveAttribute('aria-pressed', 'false')
  })

  it('7.44 agent model select is rendered with current value', async () => {
    render(<SettingsTab />)
    await waitFor(() => {
      // Two selects may have the same value (chat_model + agent_model are both mocked)
      const selects = screen.getAllByDisplayValue('qwen2.5:7b-instruct')
      expect(selects.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('7.45 tools grid renders 6 tool cards', async () => {
    render(<SettingsTab />)
    await waitFor(() => {
      const cards = document.querySelectorAll('.settings-tool-card')
      expect(cards.length).toBe(6)
    })
  })

  it('7.46 each tool card shows its label name', async () => {
    render(<SettingsTab />)
    await waitFor(() => screen.getByText('Search KB'))
    expect(screen.getByText('List Products')).toBeInTheDocument()
    expect(screen.getByText('Compare Products')).toBeInTheDocument()
  })

  it('7.47 save button calls PUT /settings with current settings payload', async () => {
    const user = userEvent.setup()
    const putSpy = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) })

    vi.stubGlobal('fetch', vi.fn((url, opts) => {
      if (opts?.method === 'PUT') return putSpy(url, opts)
      // GET calls — return mock data
      if (url.includes('/settings/agents')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ tools: [] }) })
      if (url.includes('/settings'))        return Promise.resolve({ ok: true, json: () => Promise.resolve({ chat_model: 'gemma4:latest', top_k: 5, system_prompt: '', escalation_message: '', agent_mode: true, agent_model: 'qwen2.5:7b-instruct' }) })
      if (url.includes('/models'))          return Promise.resolve({ ok: true, json: () => Promise.resolve({ models: [] }) })
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    }))

    render(<SettingsTab />)
    await waitFor(() => screen.getByText('Save settings'))
    await user.click(screen.getByText('Save settings'))

    await waitFor(() => expect(putSpy).toHaveBeenCalledOnce())
    const [, opts] = putSpy.mock.calls[0]
    const body = JSON.parse(opts.body)
    expect(body).toHaveProperty('agent_mode')
    expect(body).toHaveProperty('agent_model')
  })
})
