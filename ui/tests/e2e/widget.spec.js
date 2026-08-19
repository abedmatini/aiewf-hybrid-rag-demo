// Layer 4 – Playwright E2E · Widget page (tests 4.24 – 4.30)
//
// Tests the floating-action-button (FAB) chat widget on /widget-embed, including:
// panel open/close, widget-level consent gate, keyboard navigation,
// and mobile viewport behaviour.
//
// The widget renders inside a Shadow DOM attached to <faq-chat>.
// Playwright pierces shadow roots automatically when using CSS selectors,
// but ARIA-role queries don't pierce — we use .locator() with CSS for FAB/panel.
//
// NOTE: tests 4.26 (iframe) is omitted here — the panel uses inline ChatArea,
// not an iframe, in the current Web Component implementation.

import { test, expect } from '@playwright/test'

// Helper: wait for <faq-chat> to attach its shadow root and render the FAB.
// The widget is dynamically imported in WidgetEmbedTestPage so we wait for the
// element to appear in the DOM first.
async function gotoWidget(page) {
  await page.goto('/widget-embed')
  await page.evaluate(() => sessionStorage.clear())
  await page.waitForSelector('faq-chat', { timeout: 10_000 })
  // Give the shadow root a moment to render
  await page.waitForTimeout(500)
}

// Piercing shadow DOM helper — returns a locator that pierces faq-chat's shadow root
function fab(page) {
  return page.locator('faq-chat').locator('css=.kw-fab')
}

function panel(page) {
  return page.locator('faq-chat').locator('css=[role="dialog"]')
}

// 4.24 — FAB (floating action button) is visible on /widget-embed
test('4.24 FAB is visible on the widget page', async ({ page }) => {
  await gotoWidget(page)
  await expect(fab(page)).toBeVisible()
})

// 4.25 — Clicking the FAB opens the panel
test('4.25 FAB click opens panel with consent card', async ({ page }) => {
  await gotoWidget(page)
  await fab(page).click()
  await expect(panel(page)).toBeVisible()
})

// 4.26 — Accepting consent shows the chat area
test('4.26 accepting widget consent shows chat area', async ({ page }) => {
  await gotoWidget(page)
  await fab(page).click()
  // The consent card has an "I understand" button inside the shadow root
  const acceptBtn = page.locator('faq-chat').locator('css=button').filter({ hasText: /i understand/i })
  await expect(acceptBtn).toBeVisible({ timeout: 5_000 })
  await acceptBtn.click()
  // Chat textarea should appear after consent
  await expect(page.locator('faq-chat').locator('css=textarea')).toBeVisible({ timeout: 5_000 })
})

// 4.27 — Clicking the close button in the panel header closes the panel
test('4.27 clicking panel close button closes panel', async ({ page }) => {
  await gotoWidget(page)
  await fab(page).click()
  await expect(panel(page)).toBeVisible()

  // Close via the ✕ button in the panel header
  const closeBtn = page.locator('faq-chat').locator('css=.kw-panel__close')
  await closeBtn.click()
  await expect(panel(page)).not.toBeVisible()
})

// 4.28 — Escape key closes the widget panel
test('4.28 Escape key closes widget panel', async ({ page }) => {
  await gotoWidget(page)
  await fab(page).click()
  await expect(panel(page)).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(panel(page)).not.toBeVisible()
})

// 4.29 — FAB is visible at mobile viewport (375 × 667)
test('4.29 FAB visible on mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 })
  await gotoWidget(page)
  await expect(fab(page)).toBeVisible()
})

// 4.30 — Widget panel opens on mobile viewport
test('4.30 widget panel opens on mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 })
  await gotoWidget(page)
  await fab(page).click()
  await expect(panel(page)).toBeVisible()
})
