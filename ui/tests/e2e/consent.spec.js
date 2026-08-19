// Layer 4 – Playwright E2E · Consent gate (tests 4.1 – 4.6)
//
// Tests the consent gate that gates access to the chat interface.
// All tests in this file run against the Vite dev server only — no live API needed.

import { test, expect } from '@playwright/test'

// Ensure each test starts with a fresh consent state
test.beforeEach(async ({ page }) => {
  await page.goto('/')
  await page.evaluate(() => sessionStorage.clear())
  await page.reload()
  await page.waitForLoadState('networkidle')
})

// 4.1 — Chat input is disabled before consent is given
test('4.1 chat input disabled before consent', async ({ page }) => {
  const textarea = page.getByLabel('Type your message')
  await expect(textarea).toBeDisabled()
})

// 4.2 — Consent card is visible with the correct accept button text
test('4.2 consent card shows accept button', async ({ page }) => {
  const acceptBtn = page.getByRole('button', { name: /i understand/i })
  await expect(acceptBtn).toBeVisible()
})

// 4.3 — Accept button is auto-focused on mount
test('4.3 accept button is auto-focused on load', async ({ page }) => {
  // requestAnimationFrame fires shortly after mount
  const acceptBtn = page.getByRole('button', { name: /i understand/i })
  await expect(acceptBtn).toBeFocused()
})

// 4.4 — Clicking Accept removes consent card and enables the textarea
test('4.4 accept consent enables chat input', async ({ page }) => {
  await page.getByRole('button', { name: /i understand/i }).click()

  // Consent card should be gone
  await expect(page.getByRole('button', { name: /i understand/i })).not.toBeVisible()

  // Textarea should now be enabled
  const textarea = page.getByLabel('Type your message')
  await expect(textarea).toBeEnabled()
})

// 4.5 — Clicking "No thanks" shows the declined message
test('4.5 decline consent shows unavailable message', async ({ page }) => {
  await page.getByRole('button', { name: /no thanks/i }).click()

  await expect(
    page.getByText('Chat is unavailable. Refresh the page to reconsider.')
  ).toBeVisible()
})

// 4.6 — After accepting, page reload still shows consent accepted (sessionStorage persists)
// Note: sessionStorage persists through page reload (clears only on tab close / new session).
// This documents the actual browser behaviour — consent is remembered for the current tab.
test('4.6 after acceptance reload keeps consent accepted', async ({ page }) => {
  await page.getByRole('button', { name: /i understand/i }).click()
  await page.reload()
  await page.waitForLoadState('networkidle')

  // Consent was stored in sessionStorage — no consent card on reload
  await expect(page.getByRole('button', { name: /i understand/i })).not.toBeVisible()
  await expect(page.getByLabel('Type your message')).toBeEnabled()
})
