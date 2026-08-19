import { useState, useRef, useEffect } from 'react'
import Header from '../components/Header.jsx'
import ChatMessages from '../components/ChatMessages.jsx'
import ChatInput from '../components/ChatInput.jsx'
import SourcesDrawer from '../components/SourcesDrawer.jsx'
import './ChatPage.css'

const API          = import.meta.env.VITE_API_URL          || 'http://localhost:8003'
const PRIVACY_URL  = import.meta.env.VITE_PRIVACY_POLICY_URL || ''

import { trackEvent } from '../analytics.js'

export default function ChatPage() {
  const [messages, setMessages]         = useState([])
  const [streaming, setStreaming]       = useState(false)
  const [sources, setSources]           = useState([])
  const [drawerOpen, setDrawerOpen]     = useState(false)
  const [suggestions, setSuggestions]   = useState(null) // null = loading, [] = none, [...] = ready
  const [showSuggestions, setShowSuggestions] = useState(true)
  const [agentMode, setAgentMode]       = useState(true)  // loaded from settings
  const [agentModel, setAgentModel]     = useState('')
  const historyRef = useRef([])
  const inputRef    = useRef(null)  // for returning focus after drawer closes

  // Consent state — null: not answered, 'accepted', 'declined'
  const [consentStatus, setConsentStatus] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('consent') === 'preaccepted') return 'accepted'
    return sessionStorage.getItem('faq_consent') || null
  })

  // Load agent settings once on mount
  useEffect(() => {
    fetch(`${API}/settings`)
      .then(r => r.ok ? r.json() : null)
      .then(s => {
        if (s) {
          setAgentMode(s.agent_mode ?? true)
          setAgentModel(s.agent_model || '')
        }
      })
      .catch(() => {})
  }, [])

  // Fetch suggestions once consent is accepted (first-visit only)
  useEffect(() => {
    if (!showSuggestions || consentStatus !== 'accepted') return
    fetch(`${API}/suggestions?user_id=anonymous`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setSuggestions(data.suggestions || []) })
      .catch(() => {})
  }, [showSuggestions, consentStatus])

  function handleConsent(accepted) {
    const status = accepted ? 'accepted' : 'declined'
    sessionStorage.setItem('faq_consent', status)
    setConsentStatus(status)
    trackEvent(accepted ? 'consent_accepted' : 'consent_declined')
  }

  async function sendMessage(text) {
    if (!text.trim() || streaming || consentStatus !== 'accepted') return
    trackEvent('chatbot_message_sent')

    // Hide suggestion chips after first message
    if (showSuggestions) {
      setShowSuggestions(false)
    }

    const userMsg = { role: 'user', content: text }
    setMessages(prev => [...prev, userMsg])
    historyRef.current = [...historyRef.current, userMsg]

    setMessages(prev => [...prev, { role: 'assistant', content: '', pending: true }])
    setStreaming(true)

    const pendingSources = []
    const pendingToolSteps = []
    let fullContent = ''
    let isEscalation = false

    try {
      const resp = await fetch(`${API}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-consent-given': 'true',
        },
        body: JSON.stringify({
          message: text,
          history: historyRef.current.slice(-20),
          user_id: 'anonymous',
          agent_mode: agentMode,
        }),
      })

      const reader = resp.body.getReader()
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
              if (last && last.name === event.name) {
                last.result = event.result
              }
              setMessages(prev => {
                const next = [...prev]
                next[next.length - 1] = { role: 'assistant', content: fullContent, pending: true, toolSteps: [...pendingToolSteps] }
                return next
              })
            } else if (event.type === 'escalation') {
              fullContent = event.content
              isEscalation = true
              trackEvent('chatbot_escalation')
              setMessages(prev => {
                const next = [...prev]
                next[next.length - 1] = { role: 'assistant', content: fullContent, pending: true, escalation: true }
                return next
              })
            } else if (event.type === 'error') {
              fullContent = `Error: ${event.detail}`
            }
          } catch {}
        }
      }
    } catch (err) {
      fullContent = `Connection error: ${err.message}`
    }

    setMessages(prev => {
      const next = [...prev]
      next[next.length - 1] = {
        role: 'assistant',
        content: fullContent || '\u2026',
        pending: false,
        escalation: isEscalation,
        sources: pendingSources.length > 0 ? pendingSources : undefined,
        toolSteps: pendingToolSteps.length > 0 ? pendingToolSteps : undefined,
      }
      return next
    })
    historyRef.current = [...historyRef.current, { role: 'assistant', content: fullContent }]

    if (pendingSources.length > 0) {
      setSources(pendingSources)
      setDrawerOpen(true)
      trackEvent('chatbot_sources_opened')
    }

    setStreaming(false)
  }

  return (
    <div className="chat-page">
      <Header />
      {agentMode && (
        <div className="chat-agent-badge" title={`Agent model: ${agentModel}`}>
          <span className="chat-agent-badge__dot" />
          Agent mode
          {agentModel && <span className="chat-agent-badge__model">{agentModel}</span>}
        </div>
      )}
      <main className="chat-page__main">
        <ChatMessages
          messages={messages}
          consent={consentStatus}
          onConsent={handleConsent}
          suggestions={suggestions}
          showSuggestions={showSuggestions}
          onSuggest={sendMessage}
        />
        <ChatInput
          ref={inputRef}
          onSend={sendMessage}
          disabled={streaming || consentStatus !== 'accepted'}
          placeholder={
            consentStatus !== 'accepted'
              ? 'Accept the terms above to start chatting…'
              : undefined
          }
        />
        <p className="chat-disclaimer">
          This assistant provides approved product information only. It is not a substitute for
          professional medical advice.{' '}
          {PRIVACY_URL && (
            <a href={PRIVACY_URL} target="_blank" rel="noopener noreferrer" className="chat-disclaimer__link">
              Privacy policy
            </a>
          )}
        </p>
      </main>
      <SourcesDrawer
        open={drawerOpen}
        sources={sources}
        onClose={() => setDrawerOpen(false)}
        returnFocusRef={inputRef}
      />
    </div>
  )
}
