import { useEffect, useRef } from 'react'
import './SourcesDrawer.css'

export default function SourcesDrawer({ open, sources, onClose, returnFocusRef }) {
  const drawerRef = useRef(null)
  const closeRef  = useRef(null)

  // Move focus to close button when drawer opens
  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => closeRef.current?.focus())
    }
  }, [open])

  function handleClose() {
    onClose()
    // Return focus to wherever it was before the drawer opened
    requestAnimationFrame(() => returnFocusRef?.current?.focus())
  }

  // Full focus trap — Tab cycles within drawer, Escape closes it
  function handleKeyDown(e) {
    if (e.key === 'Escape') {
      handleClose()
      return
    }
    if (e.key !== 'Tab') return

    const focusable = drawerRef.current?.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )
    if (!focusable || focusable.length === 0) return

    const first = focusable[0]
    const last  = focusable[focusable.length - 1]

    if (e.shiftKey) {
      if (document.activeElement === first) {
        e.preventDefault()
        last.focus()
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
  }

  if (!open) return null

  return (
    <>
      <div className="drawer-overlay" onClick={handleClose} aria-hidden="true" />
      <aside
        ref={drawerRef}
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Retrieved sources"
        onKeyDown={handleKeyDown}
      >
        <div className="drawer-header">
          <span>📎 Sources ({sources.length} chunk{sources.length !== 1 ? 's' : ''})</span>
          <button
            ref={closeRef}
            className="drawer-close"
            onClick={handleClose}
            aria-label="Close sources panel"
          >
            ✕
          </button>
        </div>
        <div className="drawer-body">
          {sources.map((s, i) => (
            <div key={i} className="source-card">
              <div className="source-meta">
                <strong>{s.filename}</strong>
                {s.section && <span className="source-section"> › {s.section}</span>}
              </div>
              <p className="source-content">{s.content}</p>
            </div>
          ))}
        </div>
      </aside>
    </>
  )
}
