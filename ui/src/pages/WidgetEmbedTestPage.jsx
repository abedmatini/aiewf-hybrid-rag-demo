import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import './WidgetEmbedTestPage.css'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8003'

/**
 * Test harness for the embeddable (non-iframe) chat widget.
 *
 * Dynamically imports widget-embed.jsx, which registers the <faq-chat>
 * Web Component and auto-injects the FAB into document.body — exactly as it
 * behaves when a host site adds the <script> tag.
 */
export default function WidgetEmbedTestPage() {
  useEffect(() => {
    let el

    import('../widget/widget-embed.jsx').then(() => {
      if (document.querySelector('faq-chat')) return
      el = document.createElement('faq-chat')
      el.setAttribute('api-url', API)
      document.body.appendChild(el)
    })

    return () => { el?.remove() }
  }, [])

  return (
    <div className="wet-page">
      <header className="wet-header">
        <Link to="/" className="wet-header__back">← Back to Help Centre</Link>
        <span className="wet-header__label">Widget embed demo</span>
      </header>

      <section className="wet-hero">
        <h1 className="wet-hero__title">FAQ assistant on any page</h1>
        <p className="wet-hero__sub">
          This mock host page shows the floating <code>&lt;faq-chat&gt;</code> widget —
          open the chat button at the bottom-right to ask questions from your indexed FAQ documents.
        </p>
      </section>

      <section className="wet-content">
        <h2 className="wet-section-title">Example questions</h2>
        <ul className="wet-examples">
          <li>When is the next scheduled maintenance?</li>
          <li>Will VPN be available during the outage?</li>
          <li>How do I reset my password?</li>
        </ul>
        <p className="wet-content__hint">
          Upload FAQ content in <Link to="/admin">Admin → Documents</Link>, then try the widget here.
        </p>
      </section>

      <div className="wet-dev-banner" role="note">
        <span>
          <strong>Dev mode</strong> — Shadow DOM widget, no iframe · API <code>{API}</code>
        </span>
        <button
          type="button"
          className="wet-dev-reset"
          onClick={() => {
            localStorage.removeItem('faq_widget_consent')
            document.querySelector('faq-chat')?.remove()
            window.location.reload()
          }}
        >
          Reset consent
        </button>
      </div>
    </div>
  )
}
