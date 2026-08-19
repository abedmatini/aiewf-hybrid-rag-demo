// Layer 4 – Playwright E2E · Chat flow (tests 4.7 – 4.12)
//
// Tests the core chat interaction loop.
// The FastAPI /chat endpoint is intercepted with a Playwright route mock so these
// tests run without a live API — only the Vite dev server is required.

import { test, expect } from '@playwright/test'

// ── SSE mock helpers ────────────────────────────────────────────────────────

/** Standard token-only chat response */
function mockChatToken(page, content = 'Vitamin D helps with calcium absorption.') {
  return page.route('**/chat', route =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream; charset=utf-8',
      headers: { 'Cache-Control': 'no-cache' },
      body: `data: {"type":"token","content":${JSON.stringify(content)}}\n\ndata: {"type":"done"}\n\n`,
    })
  )
}

/** Escalation chat response */
function mockChatEscalation(page) {
  return page.route('**/chat', route =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream; charset=utf-8',
      headers: { 'Cache-Control': 'no-cache' },
      body: 'data: {"type":"escalation","content":"Please consult a healthcare professional."}\n\ndata: {"type":"done"}\n\n',
    })
  )
}

// ── Per-test setup ──────────────────────────────────────────────────────────

async function gotoAndAccept(page) {
  await page.goto('/')
  await page.evaluate(() => sessionStorage.clear())
  await page.reload()
  await page.waitForLoadState('networkidle')
  await page.getByRole('button', { name: /i understand/i }).click()
  await expect(page.getByLabel('Type your message')).toBeEnabled()
}

// ── Tests ───────────────────────────────────────────────────────────────────

// 4.7 — After accepting consent, type a question and receive a bot reply
test('4.7 send message and receive bot response', async ({ page }) => {
  await mockChatToken(page)
  await gotoAndAccept(page)

  await page.getByLabel('Type your message').fill('What is vitamin D?')
  await page.getByLabel('Send message').click()

  // Bot response should appear in the chat log
  await expect(
    page.getByRole('log').getByText('Vitamin D helps with calcium absorption.')
  ).toBeVisible({ timeout: 10_000 })
})

// 4.8 — Send button shows streaming indicator while waiting for response
test('4.8 send button shows streaming indicator during response', async ({ page }) => {
  // Slow mock: keep route handler open until we check the UI
  let resolveMock
  const mockDone = new Promise(r => { resolveMock = r })

  await page.route('**/chat', async route => {
    // Wait until the test signals it has checked the streaming state
    await mockDone
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream; charset=utf-8',
      headers: { 'Cache-Control': 'no-cache' },
      body: 'data: {"type":"token","content":"Answer"}\n\ndata: {"type":"done"}\n\n',
    })
  })

  await gotoAndAccept(page)
  await page.getByLabel('Type your message').fill('Test question')

  // Click send — the fetch starts; our route is pending
  page.getByLabel('Send message').click() // intentionally no await

  // While streaming, the send button shows '…'
  await expect(page.getByLabel('Send message')).toHaveText('…', { timeout: 5_000 })

  // Let the mock respond
  resolveMock()

  await expect(page.getByRole('log').getByText('Answer')).toBeVisible({ timeout: 10_000 })
})

// 4.9 — Chat textarea is disabled while a response is streaming
test('4.9 textarea disabled while streaming', async ({ page }) => {
  let resolveMock
  const mockDone = new Promise(r => { resolveMock = r })

  await page.route('**/chat', async route => {
    await mockDone
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream; charset=utf-8',
      headers: { 'Cache-Control': 'no-cache' },
      body: 'data: {"type":"token","content":"Answer"}\n\ndata: {"type":"done"}\n\n',
    })
  })

  await gotoAndAccept(page)
  await page.getByLabel('Type your message').fill('Test')
  page.getByLabel('Send message').click()

  // Textarea should be disabled during streaming
  await expect(page.getByLabel('Type your message')).toBeDisabled({ timeout: 5_000 })

  resolveMock()

  // Textarea re-enabled after response completes
  await expect(page.getByLabel('Type your message')).toBeEnabled({ timeout: 10_000 })
})

// 4.10 — Medical query triggers escalation badge
test('4.10 medical query shows escalation badge', async ({ page }) => {
  await mockChatEscalation(page)
  await gotoAndAccept(page)

  await page.getByLabel('Type your message').fill('Is it safe to take 10 g of paracetamol?')
  await page.getByLabel('Send message').click()

  await expect(page.locator('.message-escalation-badge')).toBeVisible({ timeout: 10_000 })
})

// 4.11 — Pressing Enter (without Shift) submits the message
test('4.11 Enter key submits message', async ({ page }) => {
  await mockChatToken(page)
  await gotoAndAccept(page)

  await page.getByLabel('Type your message').fill('What is vitamin D?')
  await page.keyboard.press('Enter')

  await expect(
    page.getByRole('log').getByText('Vitamin D helps with calcium absorption.')
  ).toBeVisible({ timeout: 10_000 })
})

// 4.12 — Send button is disabled when the textarea is empty
test('4.12 send button disabled for empty message', async ({ page }) => {
  await gotoAndAccept(page)

  // Textarea is empty by default
  await expect(page.getByLabel('Send message')).toBeDisabled()

  // Type something — button enables
  await page.getByLabel('Type your message').fill('Hello')
  await expect(page.getByLabel('Send message')).toBeEnabled()

  // Clear it — button disables again
  await page.getByLabel('Type your message').fill('')
  await expect(page.getByLabel('Send message')).toBeDisabled()
})
