import { useState, useEffect } from 'react'
import './SettingsTab.css'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8003'

const TOOL_LABELS = {
  search_kb:        { icon: '🔍', label: 'Search KB' },
  list_products:    { icon: '📋', label: 'List Products' },
  get_product_info: { icon: '📄', label: 'Product Info' },
  compare_products: { icon: '⚖️', label: 'Compare Products' },
  get_current_date: { icon: '📅', label: 'Current Date' },
  calculate:        { icon: '🧮', label: 'Calculate' },
}

export default function SettingsTab() {
  const [settings, setSettings] = useState({
    chat_model: '', top_k: 5, system_prompt: '', escalation_message: '',
    agent_mode: true, agent_model: 'qwen2.5:7b-instruct',
    guard_model_enabled: false, guard_model: 'llama-guard3:1b',
    domain: 'health_faq',
  })
  const [models, setModels]   = useState([])
  const [tools, setTools]     = useState([])
  const [loading, setLoading]   = useState(true)
  const [saving, setSaving]     = useState(false)
  const [saveMsg, setSaveMsg]   = useState('')

  useEffect(() => {
    Promise.all([
      fetch(`${API}/settings`).then(r => r.json()),
      fetch(`${API}/models`).then(r => r.json()),
      fetch(`${API}/settings/agents`).then(r => r.json()),
    ])
      .then(([s, m, a]) => {
        setSettings(s)
        setModels(m.models || [])
        setTools(a.tools || [])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  function patch(key, value) {
    setSettings(prev => ({ ...prev, [key]: value }))
    setSaveMsg('')
  }

  async function save() {
    setSaving(true)
    setSaveMsg('')
    try {
      const resp = await fetch(`${API}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      })
      if (!resp.ok) throw new Error('Save failed')
      setSaveMsg('✓ Settings saved')
    } catch (err) {
      setSaveMsg(`Error: ${err.message}`)
    }
    setSaving(false)
  }

  if (loading) return <p className="settings-loading">Loading…</p>

  return (
    <div className="settings-tab">
      {/* ── LLM configuration ──────────────────────────────── */}
      <section className="settings-card">
        <h2 className="settings-card__heading">LLM configuration</h2>
        <p className="settings-card__hint">
          Changes take effect on the next chat request — no API restart required.
        </p>

        <label className="settings-field">
          <span className="settings-field__label">Chat model</span>
          <span className="settings-field__sub">
            Pulled from the live Ollama instance at <code>{API.replace('/api', '')}</code>
          </span>
          <select
            className="settings-field__select"
            value={settings.chat_model}
            onChange={e => patch('chat_model', e.target.value)}
          >
            {models.length === 0 && (
              <option value={settings.chat_model}>{settings.chat_model}</option>
            )}
            {models.map(m => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </label>

        <label className="settings-field">
          <span className="settings-field__label">Top-K chunks</span>
          <span className="settings-field__sub">
            How many document excerpts to retrieve per answer (1 – 20)
          </span>
          <input
            className="settings-field__number"
            type="number"
            min="1"
            max="20"
            value={settings.top_k}
            onChange={e => patch('top_k', parseInt(e.target.value, 10))}
          />
        </label>
      </section>

      {/* ── Agent mode ──────────────────────────────────────── */}
      <section className="settings-card">
        <h2 className="settings-card__heading">Agent mode</h2>
        <p className="settings-card__hint">
          When on, the LLM autonomously decides which tools to call before answering.
          When off, chat falls back to direct RAG (retrieve → answer, no tool loop).
        </p>

        <div className="settings-field settings-field--row">
          <div>
            <span className="settings-field__label">Enable agent mode</span>
            <span className="settings-field__sub">
              {settings.agent_mode
                ? 'Agent is active — tool calls are visible in the chat'
                : 'Agent is off — direct RAG only'}
            </span>
          </div>
          <button
            className={`settings-toggle ${settings.agent_mode ? 'settings-toggle--on' : 'settings-toggle--off'}`}
            onClick={() => patch('agent_mode', !settings.agent_mode)}
            aria-pressed={settings.agent_mode}
            role="switch"
          >
            <span className="settings-toggle__track" />
            <span className="settings-toggle__label">
              {settings.agent_mode ? 'ON' : 'OFF'}
            </span>
          </button>
        </div>

        <label className="settings-field" style={{ marginTop: '16px' }}>
          <span className="settings-field__label">Agent model</span>
          <span className="settings-field__sub">
            Must support native function calling (e.g. qwen2.5:7b-instruct). Separate from the chat model.
          </span>
          <select
            className="settings-field__select"
            value={settings.agent_model}
            onChange={e => patch('agent_model', e.target.value)}
          >
            {models.length === 0 && (
              <option value={settings.agent_model}>{settings.agent_model}</option>
            )}
            {models.map(m => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </label>

        {/* ── Available tools ── */}
        <div className="settings-tools">
          <span className="settings-tools__heading">Available tools ({tools.length})</span>
          <div className="settings-tools__grid">
            {tools.map(tool => {
              const meta = TOOL_LABELS[tool.name] || { icon: '⚙️', label: tool.name }
              return (
                <div key={tool.name} className="settings-tool-card">
                  <span className="settings-tool-card__icon">{meta.icon}</span>
                  <div className="settings-tool-card__body">
                    <span className="settings-tool-card__name">{meta.label}</span>
                    <span className="settings-tool-card__desc">{tool.description}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </section>

      {/* ── Domain Pack ─────────────────────────────────────── */}
      <section className="settings-card">
        <h2 className="settings-card__heading">Domain Pack</h2>
        <p className="settings-card__hint">
          Controls which guardrails run on every message. Switch without restarting the API —
          takes effect on the next chat request.
        </p>

        <label className="settings-field">
          <span className="settings-field__label">Active domain</span>
          <select
            className="settings-field__select"
            value={settings.domain}
            onChange={e => patch('domain', e.target.value)}
          >
            <option value="health_faq">Health FAQ (informational) — answers general health questions, blocks personal diagnosis</option>
            <option value="health">Health (strict) — blocks all medical discussion (for product chatbots)</option>
            <option value="hr">HR &amp; Workplace — for HR policy and employment chatbots</option>
            <option value="ecommerce">E-Commerce — for product shopping chatbots</option>
          </select>
        </label>

        <div className="settings-card__hint" style={{ marginTop: '10px', fontStyle: 'normal' }}>
          {settings.domain === 'health_faq' && (
            <span>✅ <strong>Health FAQ</strong>: allows "What are the symptoms of appendicitis?" — blocks "Do I have appendicitis?"</span>
          )}
          {settings.domain === 'health' && (
            <span>🚫 <strong>Health strict</strong>: blocks all medical/health discussion. Use for product or retail chatbots only.</span>
          )}
          {settings.domain === 'hr' && (
            <span>🏢 <strong>HR</strong>: blocks individual legal/grievance actions. Allows general HR policy questions.</span>
          )}
          {settings.domain === 'ecommerce' && (
            <span>🛍️ <strong>E-Commerce</strong>: blocks PII, payment data, and off-topic requests. Allows product queries.</span>
          )}
        </div>
      </section>

      {/* ── Safety guard model ──────────────────────────────── */}
      <section className="settings-card">
        <h2 className="settings-card__heading">Safety guard model</h2>
        <p className="settings-card__hint">
          An LLM-based safety classifier (e.g. Llama Guard 3) that screens every user message
          and bot answer for unsafe content the deterministic rules might miss. Runs locally via
          Ollama and fails open — if the model is unreachable, the chat is never blocked.
        </p>

        <div className="settings-field settings-field--row">
          <div>
            <span className="settings-field__label">Enable guard model</span>
            <span className="settings-field__sub">
              {settings.guard_model_enabled
                ? 'Guard model is screening input and output'
                : 'Guard model is off — deterministic guards only'}
            </span>
          </div>
          <button
            className={`settings-toggle ${settings.guard_model_enabled ? 'settings-toggle--on' : 'settings-toggle--off'}`}
            onClick={() => patch('guard_model_enabled', !settings.guard_model_enabled)}
            aria-pressed={settings.guard_model_enabled}
            role="switch"
          >
            <span className="settings-toggle__track" />
            <span className="settings-toggle__label">
              {settings.guard_model_enabled ? 'ON' : 'OFF'}
            </span>
          </button>
        </div>

        <label className="settings-field" style={{ marginTop: '16px' }}>
          <span className="settings-field__label">Guard model</span>
          <span className="settings-field__sub">
            Pull it first with <code>ollama pull llama-guard3:1b</code>. Any moderation-tuned model works.
          </span>
          <select
            className="settings-field__select"
            value={settings.guard_model}
            onChange={e => patch('guard_model', e.target.value)}
            disabled={!settings.guard_model_enabled}
          >
            {!models.includes(settings.guard_model) && (
              <option value={settings.guard_model}>{settings.guard_model}</option>
            )}
            {models.map(m => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </label>
      </section>

      {/* ── System prompt ───────────────────────────────────── */}
      <section className="settings-card">
        <h2 className="settings-card__heading">System prompt</h2>
        <p className="settings-card__hint">
          The instruction the LLM receives before every user message. Edit to change the bot's
          tone, persona, or response style.
        </p>
        <textarea
          className="settings-field__textarea"
          value={settings.system_prompt}
          onChange={e => patch('system_prompt', e.target.value)}
          rows={8}
          spellCheck={false}
        />
      </section>
      {/* ── Escalation message ────────────────────────────── */}
      <section className="settings-card">
        <h2 className="settings-card__heading">Escalation message</h2>
        <p className="settings-card__hint">
          Shown whenever a guardrail blocks a query for the active domain (e.g. personal
          medical advice, individual legal/grievance action, or coerced commitments).
          The LLM and knowledge base are bypassed entirely — only this message is returned.
          Crisis/self-harm messages use their own built-in helpline response.
        </p>
        <textarea
          className="settings-field__textarea"
          value={settings.escalation_message}
          onChange={e => patch('escalation_message', e.target.value)}
          rows={4}
          spellCheck={false}
        />
      </section>
      {/* ── Save ───────────────────────────────────────────── */}
      <div className="settings-footer">
        <button className="settings-save-btn" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save settings'}
        </button>
        {saveMsg && (
          <span className={`settings-save-msg ${saveMsg.startsWith('Error') ? 'settings-save-msg--error' : 'settings-save-msg--ok'}`}>
            {saveMsg}
          </span>
        )}
      </div>
    </div>
  )
}
