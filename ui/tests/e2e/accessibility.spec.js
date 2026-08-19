// Layer 4 – Playwright E2E · Accessibility (tests 4.18 – 4.20)
//
// Verifies key ARIA roles and keyboard-accessible focus behaviour across the app.
// No live API required — all tests run against the Vite dev server only.

import { test, expect } from '@playwright/test'

// 4.18 — Chat log container has role="log" and aria-live="polite"
// role="log" is only rendered once there is at least one message — send a mocked
// chat message first so the log element appears in the DOM.
test('4.18 chat log has role=log with aria-live=polite', async ({ page }) => {
  // Mock the chat endpoint so no live API is needed
  await page.route('**/chat', route =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream; charset=utf-8',
      headers: { 'Cache-Control': 'no-cache' },
      body: `data: {"type":"token","content":"Hello"}\n\ndata: {"type":"done"}\n\n`,
    })
  )

  await page.goto('/')
  await page.evaluate(() => sessionStorage.clear())
  await page.reload()
  await page.waitForLoadState('networkidle')

  // Accept consent so the chat interface is rendered
  await page.getByRole('button', { name: /i understand/i }).click()
  await expect(page.getByLabel('Type your message')).toBeEnabled()

  // Send a message — once a message exists the log element is mounted
  await page.getByLabel('Type your message').fill('Hello')
  await page.getByLabel('Send message').click()
  await expect(page.getByLabel('Type your message')).toBeEnabled({ timeout: 10_000 })

  // The chat log must have role="log" and aria-live="polite" for screen readers
  const chatLog = page.getByRole('log')
  await expect(chatLog).toBeVisible()
  await expect(chatLog).toHaveAttribute('aria-live', 'polite')
})

// 4.19 — Admin tablist uses correct ARIA structure
test('4.19 admin tablist has correct ARIA structure', async ({ page }) => {
  await page.goto('/admin')
  await page.waitForLoadState('networkidle')

  // Tablist container
  const tablist = page.getByRole('tablist', { name: /admin sections/i })
  await expect(tablist).toBeVisible()

  // Three tabs with role="tab"
  const tabs = page.getByRole('tab')
  await expect(tabs).toHaveCount(3)

  // Documents tab is selected by default
  const documentsTab = page.getByRole('tab', { name: 'Documents' })
  await expect(documentsTab).toHaveAttribute('aria-selected', 'true')

  // Active panel is labelled by the active tab
  const panel = page.getByRole('tabpanel')
  await expect(panel).toHaveAttribute('aria-labelledby', 'tab-documents')
})

// 4.20 — Consent card accept button is auto-focused when the page loads
test('4.20 consent accept button auto-focused on mount', async ({ page }) => {
  await page.goto('/')
  await page.evaluate(() => sessionStorage.clear())
  await page.reload()
  await page.waitForLoadState('networkidle')

  // requestAnimationFrame has fired by the time networkidle settles
  const acceptBtn = page.getByRole('button', { name: /i understand/i })
  await expect(acceptBtn).toBeFocused()
})
