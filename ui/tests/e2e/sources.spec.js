// Layer 4 – Playwright E2E · Sources drawer (tests 4.13 – 4.17)
//
// Tests the SourcesDrawer that slides open when the API returns RAG chunk events.
// The /chat endpoint is mocked to return a chunk + token response without a live API.

import { test, expect } from '@playwright/test'

// ── Mock helper ─────────────────────────────────────────────────────────────

/** RAG response: one chunk (source) followed by a token answer */
function mockChatWithSources(page) {
  return page.route('**/chat', route =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream; charset=utf-8',
      headers: { 'Cache-Control': 'no-cache' },
      body: [
        'data: {"type":"chunk","filename":"vitaminD.pdf","section":"Overview","content":"Vitamin D aids calcium absorption."}\n',
        '\n',
        'data: {"type":"token","content":"Vitamin D is essential for bone health."}\n',
        '\n',
        'data: {"type":"done"}\n',
        '\n',
      ].join(''),
    })
  )
}

async function gotoAcceptAndSend(page, message = 'What is vitamin D?') {
  await page.goto('/')
  await page.evaluate(() => sessionStorage.clear())
  await page.reload()
  await page.waitForLoadState('networkidle')
  await page.getByRole('button', { name: /i understand/i }).click()
  await expect(page.getByLabel('Type your message')).toBeEnabled()
  await page.getByLabel('Type your message').fill(message)
  await page.getByLabel('Send message').click()
  // Wait for streaming to finish
  await expect(page.getByLabel('Type your message')).toBeEnabled({ timeout: 10_000 })
}

// ── Tests ───────────────────────────────────────────────────────────────────

// 4.13 — A RAG response with chunk events opens the sources drawer
test('4.13 sources drawer opens after RAG response', async ({ page }) => {
  await mockChatWithSources(page)
  await gotoAcceptAndSend(page)

  await expect(
    page.getByRole('dialog', { name: /retrieved sources/i })
  ).toBeVisible({ timeout: 10_000 })
})

// 4.14 — Sources drawer has correct ARIA attributes (role, aria-modal, aria-label)
test('4.14 sources drawer has correct ARIA attributes', async ({ page }) => {
  await mockChatWithSources(page)
  await gotoAcceptAndSend(page)

  const drawer = page.getByRole('dialog', { name: /retrieved sources/i })
  await expect(drawer).toBeVisible({ timeout: 10_000 })
  await expect(drawer).toHaveAttribute('aria-modal', 'true')
  await expect(drawer).toHaveAttribute('aria-label', 'Retrieved sources')
})

// 4.15 — Closing the drawer returns focus to the chat textarea
test('4.15 close drawer returns focus to textarea', async ({ page }) => {
  await mockChatWithSources(page)
  await gotoAcceptAndSend(page)

  const drawer = page.getByRole('dialog', { name: /retrieved sources/i })
  await expect(drawer).toBeVisible({ timeout: 10_000 })

  await page.getByRole('button', { name: /close sources panel/i }).click()

  await expect(drawer).not.toBeVisible()
  await expect(page.getByLabel('Type your message')).toBeFocused()
})

// 4.16 — Escape key closes the sources drawer
test('4.16 Escape key closes sources drawer', async ({ page }) => {
  await mockChatWithSources(page)
  await gotoAcceptAndSend(page)

  const drawer = page.getByRole('dialog', { name: /retrieved sources/i })
  await expect(drawer).toBeVisible({ timeout: 10_000 })

  await page.keyboard.press('Escape')

  await expect(drawer).not.toBeVisible()
})

// 4.17 — Tab key cycles focus within the sources drawer (focus trap)
test('4.17 Tab cycles focus within sources drawer', async ({ page }) => {
  await mockChatWithSources(page)
  await gotoAcceptAndSend(page)

  const drawer = page.getByRole('dialog', { name: /retrieved sources/i })
  await expect(drawer).toBeVisible({ timeout: 10_000 })

  // Close button receives focus when drawer opens
  const closeBtn = page.getByRole('button', { name: /close sources panel/i })
  await expect(closeBtn).toBeFocused()

  // Tab from the only focusable element should wrap back to it
  await page.keyboard.press('Tab')
  await expect(closeBtn).toBeFocused()
})
