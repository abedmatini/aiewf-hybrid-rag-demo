import { useState, useEffect, useRef } from 'react'
import './ChunksModal.css'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8003'

export default function ChunksModal({ doc, onClose }) {
  const [chunks, setChunks]         = useState([])
  const [loading, setLoading]       = useState(true)
  const [editingId, setEditingId]   = useState(null)
  const [editContent, setEditContent] = useState('')
  const [saving, setSaving]         = useState(false)
  const [saveMsg, setSaveMsg]       = useState('')   // { id, text, ok }
  const textareaRef = useRef(null)

  useEffect(() => {
    loadChunks()
  }, [doc.id])

  useEffect(() => {
    if (editingId && textareaRef.current) {
      textareaRef.current.focus()
      textareaRef.current.selectionStart = textareaRef.current.value.length
    }
  }, [editingId])

  async function loadChunks() {
    setLoading(true)
    try {
      const resp = await fetch(`${API}/documents/${doc.id}/chunks`)
      if (resp.ok) setChunks(await resp.json())
    } catch {}
    setLoading(false)
  }

  function startEdit(chunk) {
    setEditingId(chunk.id)
    setEditContent(chunk.content)
    setSaveMsg('')
  }

  function cancelEdit() {
    setEditingId(null)
    setEditContent('')
    setSaveMsg('')
  }

  async function saveEdit(chunkId) {
    if (!editContent.trim()) return
    setSaving(true)
    setSaveMsg('')
    try {
      const resp = await fetch(`${API}/documents/${doc.id}/chunks/${chunkId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: editContent }),
      })
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}))
        throw new Error(err.detail || 'Save failed')
      }
      // Update local state
      setChunks(prev =>
        prev.map(c => c.id === chunkId ? { ...c, content: editContent } : c)
      )
      setSaveMsg({ id: chunkId, text: 'Saved & re-embedded', ok: true })
      setEditingId(null)
    } catch (err) {
      setSaveMsg({ id: chunkId, text: err.message, ok: false })
    }
    setSaving(false)
  }

  // Close on Escape
  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="chunks-overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="chunks-modal" role="dialog" aria-modal="true">

        {/* ── Header ───────────────────────────────────────── */}
        <div className="chunks-modal__header">
          <div className="chunks-modal__title">
            <span className="chunks-modal__filename" title={doc.filename}>{doc.filename}</span>
            <span className="chunks-modal__meta">
              {doc.strategy} · {chunks.length} chunk{chunks.length !== 1 ? 's' : ''}
            </span>
          </div>
          <button className="chunks-modal__close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {/* ── Body ─────────────────────────────────────────── */}
        <div className="chunks-modal__body">
          {loading ? (
            <p className="chunks-loading">Loading chunks…</p>
          ) : chunks.length === 0 ? (
            <p className="chunks-empty">No chunks found for this document.</p>
          ) : (
            chunks.map(chunk => (
              <div key={chunk.id} className="chunk-card">
                <div className="chunk-card__meta">
                  <span className="chunk-card__index">#{chunk.chunk_index + 1}</span>
                  {chunk.section_heading && (
                    <span className="chunk-card__heading">{chunk.section_heading}</span>
                  )}
                  <div className="chunk-card__actions">
                    {saveMsg && saveMsg.id === chunk.id && (
                      <span className={`chunk-save-msg ${saveMsg.ok ? 'chunk-save-msg--ok' : 'chunk-save-msg--error'}`}>
                        {saveMsg.text}
                      </span>
                    )}
                    {editingId === chunk.id ? (
                      <>
                        <button
                          className="chunk-btn chunk-btn--save"
                          onClick={() => saveEdit(chunk.id)}
                          disabled={saving}
                        >
                          {saving ? 'Saving…' : 'Save'}
                        </button>
                        <button
                          className="chunk-btn chunk-btn--cancel"
                          onClick={cancelEdit}
                          disabled={saving}
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <button
                        className="chunk-btn chunk-btn--edit"
                        onClick={() => startEdit(chunk)}
                      >
                        Edit
                      </button>
                    )}
                  </div>
                </div>

                {editingId === chunk.id ? (
                  <textarea
                    ref={textareaRef}
                    className="chunk-card__textarea"
                    value={editContent}
                    onChange={e => setEditContent(e.target.value)}
                    rows={Math.max(6, editContent.split('\n').length + 2)}
                  />
                ) : (
                  <div className="chunk-card__content">{chunk.content}</div>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
