// Layer 4 – Playwright E2E · Admin page (tests 4.21 – 4.23)
//
// Tests tab navigation, panel switching, and navigation on the admin page.
// API calls (settings, analytics data) are mocked so no live FastAPI server is needed.

import { test, expect } from '@playwright/test'

// Mock API endpoints the admin components may fetch
async function mockAdminApi(page) {
  await page.route('**/settings', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        model: 'gemma4:latest',
        system_prompt: 'You are a helpful assistant.',
        top_k: 5,
        temperature: 0.7,
      }),
    })
  )
  await page.route('**/analytics/summary', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      // Shape must match what AnalyticsTab destructures — missing keys cause
      // top_questions.map() / recent_logs.map() to throw and crash the React tree
      body: JSON.stringify({
        total_chats: 42,
        escalation_count: 3,
        escalation_rate: 0.07,
        no_match_count: 2,
        avg_duration_ms: 850,
        top_questions: [],
        recent_logs: [],
      }),
    })
  )
  // Stub the documents list endpoint
  await page.route('**/documents**', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  )
}

// 4.21 — Documents tab is the default active tab on the admin page
test('4.21 documents tab is active by default', async ({ page }) => {
  await mockAdminApi(page)
  await page.goto('/admin')
  await page.waitForLoadState('networkidle')

  await expect(page.getByRole('tab', { name: 'Documents' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab', { name: 'Settings' })).toHaveAttribute('aria-selected', 'false')
  await expect(page.getByRole('tab', { name: 'Analytics' })).toHaveAttribute('aria-selected', 'false')
})

// 4.22 — Clicking the Analytics tab switches the active panel
test('4.22 clicking Analytics tab shows analytics panel', async ({ page }) => {
  await mockAdminApi(page)
  await page.goto('/admin')
  await page.waitForLoadState('networkidle')

  await page.getByRole('tab', { name: 'Analytics' }).click()

  await expect(page.getByRole('tab', { name: 'Analytics' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab', { name: 'Documents' })).toHaveAttribute('aria-selected', 'false')

  // Panel id and labelledby must reference the analytics tab
  const panel = page.getByRole('tabpanel')
  await expect(panel).toHaveAttribute('id', 'panel-analytics')
  await expect(panel).toHaveAttribute('aria-labelledby', 'tab-analytics')
})

// 4.23 — "← Back to Chat" link navigates to the chat page
test('4.23 back to chat link navigates to root', async ({ page }) => {
  await mockAdminApi(page)
  await page.goto('/admin')
  await page.waitForLoadState('networkidle')

  await page.getByText('← Back to Chat').click()

  await expect(page).toHaveURL('/')
})
