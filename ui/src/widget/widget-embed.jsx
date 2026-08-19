/**
 * FAQ Chat — embeddable widget (no iframe).
 *
 * Registers a <faq-chat> Web Component and auto-injects it into document.body.
 * Styles are isolated in a Shadow DOM root so host-page CSS never interferes.
 *
 * Usage (script tag — auto-injects FAB):
 *   <script src="chatbot-widget.iife.js"
 *           data-api-url="https://api.example.com"
 *           data-preaccepted></script>
 *
 * Usage (declarative):
 *   <faq-chat api-url="https://api.example.com" preaccepted></faq-chat>
 *
 * Attributes:
 *   api-url       Base URL of the FAQ API  (default: http://localhost:8003)
 *   preaccepted   Present → skip the consent gate entirely
 */

import React, { useState, useRef, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import styles from './widget-embed.css?inline'

const PREVIEW_CHARS = 220

// ── Source citation chips ─────────────────────────────────────────────────────
function SourceCitations({ sources }) {
  const [open, setOpen] = useState(null)
  const [expanded, setExpanded] = useState(false)

  if (!sources || sources.length === 0) return null

  function handleChipClick(i) {
    if (open === i) { setOpen(null); setExpanded(false) }
    else            { setOpen(i);    setExpanded(false) }
  }

  return (
    <div className="kw-citations">
      <span className="kw-citations__label">Sources</span>
      {sources.map((src, i) => (
        <span key={i} className="kw-cite-wrap">
          <button
            className={`kw-cite-chip${open === i ? ' kw-cite-chip--active' : ''}`}
            onClick={() => handleChipClick(i)}
            aria-expanded={open === i}
            aria-label={`Source ${i + 1}: ${src.filename}`}
          >
            {i + 1}
          </button>
          {open === i && (
            <div className={`kw-cite-pop${expanded ? ' kw-cite-pop--expanded' : ''}`} role="tooltip">
              <div className="kw-cite-pop__hdr">
                <strong>{src.filename}</strong>
                {src.section && <span className="kw-cite-pop__sec"> › {src.section}</span>}
              </div>
              <p className="kw-cite-pop__text">
                {expanded ? src.content : src.content?.slice(0, PREVIEW_CHARS)}
                {!expanded && src.content?.length > PREVIEW_CHARS && '…'}
              </p>
              {src.content?.length > PREVIEW_CHARS && (
                <button
                  className="kw-cite-expand"
                  onClick={e => { e.stopPropagation(); setExpanded(!expanded) }}
                >
                  {expanded ? 'Show less ↑' : 'Show more ↓'}
                </button>
              )}
            </div>
          )}
        </span>
      ))}
    </div>
  )
}

// ── Consent gate ──────────────────────────────────────────────────────────────
function ConsentGate({ onAccept, onDecline }) {
  const btnRef = useRef(null)
  useEffect(() => { btnRef.current?.focus() }, [])

  return (
    <div className="kw-consent">
      <div className="kw-consent__card">
        <p className="kw-consent__title">👋 Before we begin</p>
        <p className="kw-consent__body">
          This assistant provides{' '}
          <strong>approved FAQ documents only</strong>.
          Answers are generated from uploaded help content, not general web knowledge.
        </p>
        <ul className="kw-consent__list">
          <li>Your questions are processed by an AI language model</li>
          <li>Do not share passwords, account numbers, or other sensitive data</li>
          <li>For account-specific issues, contact your support team directly</li>
        </ul>
        <div className="kw-consent__btns">
          <button ref={btnRef} className="kw-consent__accept" onClick={onAccept}>
            I understand, let's chat
          </button>
          <button className="kw-consent__decline" onClick={onDecline}>
            No thanks
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Tool steps (agent transparency) ─────────────────────────────────────────
const TOOL_LABELS = {
  search_kb:        '🔍 Search KB',
  list_products:    '📋 List Products',
  get_product_info: '📄 Product Info',
  compare_products: '⚖️ Compare',
  get_current_date: '📅 Date',
  calculate:        '🧮 Calculate',
}

function ToolSteps({ steps }) {
  const [expandedIdx, setExpandedIdx] = useState(null)
  if (!steps || steps.length === 0) return null
  return (
    <div className="kw-tool-steps">
      {steps.map((step, i) => (
        <div key={i} className={`kw-tool-step${step.result ? ' kw-tool-step--done' : ' kw-tool-step--running'}`}>
          <button
            className="kw-tool-step__hdr"
            onClick={() => setExpandedIdx(expandedIdx === i ? null : i)}
          >
            <span className="kw-tool-step__icon">{step.result ? '✓' : '⟳'}</span>
            <span>{TOOL_LABELS[step.name] || step.name}</span>
            {step.args?.query && <span className="kw-tool-step__q">"{step.args.query}"</span>}
          </button>
          {expandedIdx === i && step.result && (
            <pre className="kw-tool-step__result">{step.result}</pre>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Chat area (messages + input) ──────────────────────────────────────────────
function ChatArea({ apiUrl, consent, onConsent }) {
  const [messages, setMessages] = useState([])
  const [streaming, setStreaming] = useState(false)
  const [input, setInput]         = useState('')
  const [suggestions, setSuggestions]     = useState(null)  // null=loading, []=none, [...]=ready
  const [showSuggestions, setShowSuggestions] = useState(true)
  const [agentMode, setAgentMode]   = useState(true)
  const [agentModel, setAgentModel] = useState('')
  const historyRef = useRef([])
  const bottomRef  = useRef(null)
  const inputRef   = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Load agent settings once
  useEffect(() => {
    fetch(`${apiUrl}/settings`)
      .then(r => r.ok ? r.json() : null)
      .then(s => { if (s) { setAgentMode(s.agent_mode ?? true); setAgentModel(s.agent_model || '') } })
      .catch(() => {})
  }, [apiUrl])

  // Fetch suggestions once consent is accepted
  useEffect(() => {
    if (!showSuggestions || consent !== 'accepted') return
    fetch(`${apiUrl}/suggestions?user_id=anonymous`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setSuggestions(data.suggestions || []) })
      .catch(() => { setSuggestions([]) })
  }, [showSuggestions, consent])

  if (consent === 'declined') {
    return (
      <div className="kw-unavailable">
        Chat unavailable. Close and reopen to reconsider.
      </div>
    )
  }

  if (consent !== 'accepted') {
    return (
      <ConsentGate
        onAccept={() => onConsent('accepted')}
        onDecline={() => onConsent('declined')}
      />
    )
  }

  async function send(text) {
    if (text === undefined) text = input
    text = text.trim()
    if (!text || streaming) return
    setInput('')

    // Hide suggestion chips after first message
    if (showSuggestions) setShowSuggestions(false)

    const userMsg = { role: 'user', content: text }
    setMessages(prev => [...prev, userMsg])
    historyRef.current = [...historyRef.current, userMsg]
    setMessages(prev => [...prev, { role: 'assistant', content: '', pending: true }])
    setStreaming(true)

    const pendingSources = []
    const pendingToolSteps = []
    let fullContent  = ''
    let isEscalation = false

    try {
      const resp = await fetch(`${apiUrl}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-consent-given': 'true',
        },
        body: JSON.stringify({
          message: text,
          history: historyRef.current.slice(-20),
          user_id: 'widget-anonymous',
          agent_mode: agentMode,
        }),
      })

      const reader  = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))
            if (event.type === 'chunk') {
              pendingSources.push(event)
            } else if (event.type === 'token') {
              fullContent += event.content
              setMessages(prev => {
                const next = [...prev]
                next[next.length - 1] = { role: 'assistant', content: fullContent, pending: true, toolSteps: [...pendingToolSteps] }
                return next
              })
            } else if (event.type === 'tool_call') {
              pendingToolSteps.push({ name: event.name, args: event.args, result: null })
              setMessages(prev => {
                const next = [...prev]
                next[next.length - 1] = { role: 'assistant', content: fullContent, pending: true, toolSteps: [...pendingToolSteps] }
                return next
              })
            } else if (event.type === 'tool_result') {
              const last = pendingToolSteps[pendingToolSteps.length - 1]
              if (last && last.name === event.name) last.result = event.result
              setMessages(prev => {
                const next = [...prev]
                next[next.length - 1] = { role: 'assistant', content: fullContent, pending: true, toolSteps: [...pendingToolSteps] }
                return next
              })
            } else if (event.type === 'escalation') {
              fullContent  = event.content
              isEscalation = true
              setMessages(prev => {
                const next = [...prev]
                next[next.length - 1] = { role: 'assistant', content: fullContent, pending: true, escalation: true }
                return next
              })
            }
          } catch { /* malformed SSE line */ }
        }
      }
    } catch (err) {
      fullContent = `Connection error: ${err.message}`
    }

    setMessages(prev => {
      const next = [...prev]
      next[next.length - 1] = {
        role: 'assistant',
        content: fullContent || '…',
        pending: false,
        escalation: isEscalation,
        sources: pendingSources.length > 0 ? pendingSources : undefined,
        toolSteps: pendingToolSteps.length > 0 ? pendingToolSteps : undefined,
      }
      return next
    })
    historyRef.current = [...historyRef.current, { role: 'assistant', content: fullContent }]
    setStreaming(false)
    requestAnimationFrame(() => inputRef.current?.focus())
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  // Suggestion chips empty-state
  const isLoadingSugg = showSuggestions && suggestions === null
  const hasChips      = showSuggestions && Array.isArray(suggestions) && suggestions.length > 0

  return (
    <div className="kw-chat">        {agentMode && (
          <div className="kw-agent-badge">
            <span className="kw-agent-badge__dot" />
            Agent mode
            {agentModel && <span className="kw-agent-badge__model">{agentModel}</span>}
          </div>
        )}      <div className="kw-messages" role="log" aria-live="polite" aria-label="Chat conversation">
        {messages.length === 0 && (isLoadingSugg || hasChips) ? (
          <>
            <div className="kw-msg kw-msg--assistant">
              <div className="kw-bubble">Here are some things you can ask:</div>
            </div>
            <div className="kw-sugg-grid">
              {isLoadingSugg
                ? [0,1,2,3].map(i => <div key={i} className="kw-sugg-chip kw-sugg-chip--skeleton" />)
                : suggestions.map((q, i) => (
                    <button key={i} className="kw-sugg-chip" onClick={() => send(q)}>{q}</button>
                  ))
              }
            </div>
          </>
        ) : messages.length === 0 ? (
          <p className="kw-messages__empty">Ask a question to get started.</p>
        ) : null}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`kw-msg kw-msg--${msg.role}${msg.escalation ? ' kw-msg--escalation' : ''}`}
          >
            <div className="kw-bubble">
              {msg.escalation && (
                <span className="kw-escalation-badge">⚕ Medical escalation</span>
              )}
              {msg.role === 'assistant' && msg.toolSteps && (
                <ToolSteps steps={msg.toolSteps} />
              )}
              {msg.content || <span className="kw-cursor" />}
              {!msg.pending && msg.role === 'assistant' && (
                <SourceCitations sources={msg.sources} />
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="kw-input-row">
        <textarea
          ref={inputRef}
          className="kw-input"
          rows={1}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={streaming}
          placeholder={streaming ? 'Generating…' : 'Type a message…'}
          aria-label="Message input"
        />
        <button
          className="kw-send"
          onClick={() => send()}
          disabled={!input.trim() || streaming}
          aria-label="Send"
        >
          ↑
        </button>
      </div>
    </div>
  )
}

// ── Widget shell — FAB + collapsible panel ────────────────────────────────────
function WidgetApp({ apiUrl, preaccepted }) {
  const [open, setOpen] = useState(false)
  const [consent, setConsent] = useState(() => {
    if (preaccepted) return 'accepted'
    try { return localStorage.getItem('faq_widget_consent') || null } catch { return null }
  })

  function handleConsent(status) {
    setConsent(status)
    try { localStorage.setItem('faq_widget_consent', status) } catch { /* private browsing */ }
  }

  // Escape closes the panel
  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape' && open) setOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <div className="kw-root">
      {open && (
        <div className="kw-panel" role="dialog" aria-modal="true" aria-label="FAQ Assistant">
          <div className="kw-panel__header">
            <span className="kw-panel__title">FAQ Assistant</span>
            <button
              className="kw-panel__close"
              onClick={() => setOpen(false)}
              aria-label="Close chat"
            >
              ✕
            </button>
          </div>
          <ChatArea apiUrl={apiUrl} consent={consent} onConsent={handleConsent} />
        </div>
      )}

      <button
        className="kw-fab"
        onClick={() => setOpen(o => !o)}
        aria-label={open ? 'Close chat' : 'Open FAQ chat'}
        aria-expanded={open}
        aria-controls="kw-panel"
      >
        {open ? '✕' : '💬'}
      </button>
    </div>
  )
}

// ── Web Component ─────────────────────────────────────────────────────────────
class FAQChatWidget extends HTMLElement {
  connectedCallback() {
    // The host element itself is fixed-positioned so the panel/FAB sit bottom-right
    this.style.cssText = 'position:fixed;bottom:1.5rem;right:1.5rem;z-index:2147483647;'

    const shadow = this.attachShadow({ mode: 'open' })

    const styleEl = document.createElement('style')
    styleEl.textContent = styles
    shadow.appendChild(styleEl)

    const container = document.createElement('div')
    shadow.appendChild(container)

    const apiUrl      = this.getAttribute('api-url') || 'http://localhost:8003'
    const preaccepted = this.hasAttribute('preaccepted')

    createRoot(container).render(
      React.createElement(WidgetApp, { apiUrl, preaccepted })
    )
  }
}

if (!customElements.get('faq-chat')) {
  customElements.define('faq-chat', FAQChatWidget)
}

// ── Auto-inject when loaded via <script src="..."> ────────────────────────────
function autoInject() {
  if (document.querySelector('faq-chat')) return  // already placed declaratively

  const el     = document.createElement('faq-chat')
  const script = document.currentScript
    || document.querySelector('script[src*="chatbot-widget"]')

  if (script) {
    const apiUrl = script.getAttribute('data-api-url')
    if (apiUrl) el.setAttribute('api-url', apiUrl)
    if (script.hasAttribute('data-preaccepted')) el.setAttribute('preaccepted', '')
  }

  document.body.appendChild(el)
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', autoInject)
} else {
  autoInject()
}
