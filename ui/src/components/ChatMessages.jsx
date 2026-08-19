import { useEffect, useRef, useState } from 'react'
import './ChatMessages.css'

function ToolSteps({ steps }) {
  const [expandedIdx, setExpandedIdx] = useState(null)
  if (!steps || steps.length === 0) return null

  const TOOL_LABELS = {
    search_kb: '🔍 Search KB',
    list_products: '📋 List Products',
    get_product_info: '📄 Product Info',
    compare_products: '⚖️ Compare',
    get_current_date: '📅 Date',
    calculate: '🧮 Calculate',
  }

  return (
    <div className="tool-steps">
      {steps.map((step, i) => (
        <div key={i} className={`tool-step${step.result ? ' tool-step--done' : ' tool-step--running'}`}>
          <button
            className="tool-step__header"
            onClick={() => setExpandedIdx(expandedIdx === i ? null : i)}
            aria-expanded={expandedIdx === i}
          >
            <span className="tool-step__icon">{step.result ? '✓' : '⟳'}</span>
            <span className="tool-step__label">
              {TOOL_LABELS[step.name] || step.name}
            </span>
            {step.args?.query && (
              <span className="tool-step__query">"{step.args.query}"</span>
            )}
          </button>
          {expandedIdx === i && step.result && (
            <pre className="tool-step__result">{step.result}</pre>
          )}
        </div>
      ))}
    </div>
  )
}

function SourceCitations({ sources }) {
  const [open, setOpen] = useState(null)
  const [expanded, setExpanded] = useState(false)

  if (!sources || sources.length === 0) return null

  function handleChipClick(i) {
    if (open === i) {
      setOpen(null)
      setExpanded(false)
    } else {
      setOpen(i)
      setExpanded(false)
    }
  }

  return (
    <div className="citation-list">
      <span className="citation-label">Sources</span>
      {sources.map((src, i) => (
        <span key={i} className="citation-wrapper">
          <button
            className={`citation-chip${open === i ? ' citation-chip--active' : ''}`}
            onClick={() => handleChipClick(i)}
            aria-expanded={open === i}
            aria-label={`Source ${i + 1}: ${src.filename}`}
          >
            {i + 1}
          </button>
          {open === i && (
            <div className={`citation-popover${expanded ? ' citation-popover--expanded' : ''}`} role="tooltip">
              <div className="citation-popover__header">
                <strong>{src.filename}</strong>
                {src.section && (
                  <span className="citation-popover__section"> › {src.section}</span>
                )}
              </div>
              <p className="citation-popover__text">
                {expanded
                  ? src.content
                  : src.content?.slice(0, 220)
                }
                {!expanded && src.content?.length > 220 && '…'}
              </p>
              {src.content?.length > 220 && (
                <button
                  className="citation-expand-btn"
                  onClick={(e) => { e.stopPropagation(); setExpanded(!expanded) }}
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

export default function ChatMessages({ messages, consent, onConsent, suggestions = [], showSuggestions = false, onSuggest }) {
  const bottomRef = useRef(null)
  const acceptRef  = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Auto-focus the accept button when the consent card first appears
  useEffect(() => {
    if (consent === null) {
      requestAnimationFrame(() => acceptRef.current?.focus())
    }
  }, [consent])

  // ── Consent gate ─────────────────────────────────────────────────────────
  if (consent !== 'accepted') {
    return (
      <div className="messages messages--consent">
        <div className="consent-card">
          <h3 className="consent-card__heading">👋 Before we begin
          </h3>
          <div className="consent-card__body">
            <p>
              This assistant provides{' '}
              <strong>approved FAQ documents only</strong>.
              Answers are generated from uploaded help content, not general web knowledge.
            </p>
            <ul>
              <li>Your questions are processed by an AI language model</li>
              <li>Do not share passwords, account numbers, or other sensitive data</li>
              <li>For account-specific issues, contact your support team directly</li>
            </ul>
          </div>
          {consent === 'declined' ? (
            <p className="consent-declined-msg">
              Chat is unavailable. Refresh the page to reconsider.
            </p>
          ) : (
            <div className="consent-card__actions">
              <button
                ref={acceptRef}
                className="consent-btn consent-btn--accept"
                onClick={() => onConsent(true)}
              >
                I understand, let’s chat
              </button>
              <button
                className="consent-btn consent-btn--decline"
                onClick={() => onConsent(false)}
              >
                No thanks
              </button>
            </div>
          )}
        </div>
      </div>
    )
  }
  // ─────────────────────────────────────────────────────────────────────────

  if (messages.length === 0) {
    const isLoading = showSuggestions && suggestions === null
    const hasChips  = showSuggestions && Array.isArray(suggestions) && suggestions.length > 0

    if (isLoading || hasChips) {
      return (
        <div className="messages messages--suggestions">
          <div className="message message--assistant">
            <div className="message-bubble">
              Here are some questions you can ask to get started:
            </div>
          </div>
          {isLoading ? (
            <div className="suggestions-grid suggestions-grid--loading">
              {[0, 1, 2, 3].map(i => (
                <div key={i} className="suggestion-chip suggestion-chip--skeleton" />
              ))}
            </div>
          ) : (
            <div className="suggestions-grid">
              {suggestions.map((q, i) => (
                <button key={i} className="suggestion-chip" onClick={() => onSuggest(q)}>
                  {q}
                </button>
              ))}
            </div>
          )}
        </div>
      )
    }

    return (
      <div className="messages messages--empty">
        <p>Ask a question to get started.</p>
      </div>
    )
  }

  return (
    <div
      className="messages"
      role="log"
      aria-live="polite"
      aria-label="Chat conversation"
    >
      {messages.map((msg, i) => (
        <div key={i} className={`message message--${msg.role}${msg.escalation ? ' message--escalation' : ''}`}>
          <div className="message-bubble">
            {msg.escalation && (
              <span className="message-escalation-badge">&#9877; Medical escalation</span>
            )}
            {msg.role === 'assistant' && msg.toolSteps && (
              <ToolSteps steps={msg.toolSteps} />
            )}
            {msg.content || <span className="message-cursor" />}
            {!msg.pending && msg.role === 'assistant' && (
              <SourceCitations sources={msg.sources} />
            )}
          </div>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
