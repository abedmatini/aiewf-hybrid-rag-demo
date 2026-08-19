/**
 * GA4 analytics wrapper.
 * Only active when VITE_GA4_ID is set. All calls are no-ops otherwise.
 */

const GA_ID = import.meta.env.VITE_GA4_ID

let _initialized = false

export const GA_ENABLED = Boolean(GA_ID)

/** Inject the gtag script and configure the GA4 measurement ID. */
export function initGA() {
  if (!GA_ID || _initialized) return
  _initialized = true

  window.dataLayer = window.dataLayer || []
  window.gtag = function () { window.dataLayer.push(arguments) }
  window.gtag('js', new Date())
  window.gtag('config', GA_ID, { anonymize_ip: true })

  const script = document.createElement('script')
  script.async = true
  script.src = `https://www.googletagmanager.com/gtag/js?id=${GA_ID}`
  document.head.appendChild(script)
}

/** Fire a GA4 event. Safe to call before initGA — events are silently dropped. */
export function trackEvent(name, params = {}) {
  if (typeof window.gtag !== 'function') return
  window.gtag('event', name, params)
}
