import { useState } from 'react'
import { initGA, GA_ENABLED } from '../analytics.js'
import './CookieBanner.css'

const STORAGE_KEY = 'faq_cookies'

/**
 * Minimal cookie consent banner.
 * Only rendered when VITE_GA4_ID is set and the user hasn't yet responded.
 * Stores choice in localStorage so it persists across sessions.
 */
export default function CookieBanner() {
  const [visible, setVisible] = useState(
    () => GA_ENABLED && !localStorage.getItem(STORAGE_KEY)
  )

  if (!visible) return null

  function accept() {
    localStorage.setItem(STORAGE_KEY, 'accepted')
    initGA()
    setVisible(false)
  }

  function decline() {
    localStorage.setItem(STORAGE_KEY, 'declined')
    setVisible(false)
  }

  const privacyUrl = import.meta.env.VITE_PRIVACY_POLICY_URL || null

  return (
    <div className="cookie-banner" role="alertdialog" aria-label="Cookie consent">
      <p className="cookie-banner__text">
        We use analytics cookies to improve this service.
        {privacyUrl && (
          <>
            {' '}
            <a
              href={privacyUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="cookie-banner__link"
            >
              Privacy&nbsp;policy
            </a>
          </>
        )}
      </p>
      <div className="cookie-banner__actions">
        <button className="cookie-btn cookie-btn--accept" onClick={accept}>
          Accept cookies
        </button>
        <button className="cookie-btn" onClick={decline}>
          Decline
        </button>
      </div>
    </div>
  )
}
