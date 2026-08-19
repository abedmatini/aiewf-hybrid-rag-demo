import { useState, useEffect, useCallback } from 'react'
import './AnalyticsTab.css'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8003'

const EVENT_META = {
  chat:       { label: 'Chat',       bg: '#003087' },
  escalation: { label: 'Escalation', bg: '#f59e0b' },
  no_match:   { label: 'No match',   bg: '#6b7280' },
  empty_kb:   { label: 'Empty KB',   bg: '#ef4444' },
  error:      { label: 'Error',      bg: '#ef4444' },
}

function EventBadge({ type }) {
  const meta = EVENT_META[type] || { label: type, bg: '#6b7280' }
  return (
    <span className="event-badge" style={{ background: meta.bg }}>
      {meta.label}
    </span>
  )
}

export default function AnalyticsTab() {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API}/analytics/summary`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <p className="analytics-state">Loading analytics…</p>
  if (error)   return <p className="analytics-state analytics-state--error">Failed to load: {error}</p>

  const {
    total_chats, escalation_count, escalation_rate,
    no_match_count, avg_duration_ms, top_questions, recent_logs,
  } = data

  return (
    <div className="analytics">

      {/* ── Summary cards ──────────────────────────────────────── */}
      <div className="analytics-cards">
        <div className="analytics-card">
          <span className="analytics-card__value">{total_chats}</span>
          <span className="analytics-card__label">Total chats</span>
          <span className="analytics-card__sub">last 30 days</span>
        </div>
        <div className={`analytics-card ${escalation_rate > 20 ? 'analytics-card--warn' : ''}`}>
          <span className="analytics-card__value">{escalation_rate}%</span>
          <span className="analytics-card__label">Escalation rate</span>
          <span className="analytics-card__sub">{escalation_count} escalated</span>
        </div>
        <div className="analytics-card">
          <span className="analytics-card__value">{no_match_count}</span>
          <span className="analytics-card__label">No-match responses</span>
          <span className="analytics-card__sub">gaps in knowledge base</span>
        </div>
        <div className="analytics-card">
          <span className="analytics-card__value">
            {avg_duration_ms ? `${avg_duration_ms} ms` : '—'}
          </span>
          <span className="analytics-card__label">Avg latency</span>
          <span className="analytics-card__sub">end-to-end per turn</span>
        </div>
      </div>

      {/* ── Top questions ──────────────────────────────────────── */}
      <section className="analytics-section">
        <h2 className="analytics-section__title">Top questions (30 d)</h2>
        {top_questions.length === 0 ? (
          <p className="analytics-empty">No data yet — start chatting to see results.</p>
        ) : (
          <div className="analytics-table-wrap">
            <table className="analytics-table">
              <thead>
                <tr><th>#</th><th>Question</th><th>Count</th></tr>
              </thead>
              <tbody>
                {top_questions.map((q, i) => (
                  <tr key={i}>
                    <td className="analytics-table__rank">{i + 1}</td>
                    <td className="analytics-table__msg">{q.message}</td>
                    <td>{q.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ── Recent interactions ────────────────────────────────── */}
      <section className="analytics-section">
        <div className="analytics-section__header">
          <h2 className="analytics-section__title">Recent interactions</h2>
          <button className="analytics-refresh" onClick={load} aria-label="Refresh analytics">
            ↻ Refresh
          </button>
        </div>
        {recent_logs.length === 0 ? (
          <p className="analytics-empty">No interactions yet.</p>
        ) : (
          <div className="analytics-table-wrap">
            <table className="analytics-table">
              <thead>
                <tr><th>Time</th><th>Message</th><th>Type</th><th>Latency</th></tr>
              </thead>
              <tbody>
                {recent_logs.map(log => (
                  <tr key={log.id}>
                    <td className="analytics-table__time">
                      {new Date(log.logged_at).toLocaleString()}
                    </td>
                    <td className="analytics-table__msg">{log.message}</td>
                    <td><EventBadge type={log.event_type} /></td>
                    <td>{log.duration_ms != null ? `${log.duration_ms} ms` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

    </div>
  )
}
