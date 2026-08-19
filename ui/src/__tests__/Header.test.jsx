/**
 * Tests 7.26–7.27: Header component
 *
 * Header uses react-router-dom <Link>, so tests need a MemoryRouter wrapper.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect } from 'vitest'
import Header from '../components/Header'

function renderHeader() {
  return render(
    <MemoryRouter>
      <Header />
    </MemoryRouter>
  )
}

describe('Header', () => {
  it('7.26 renders "Widget demo" link pointing to /widget', () => {
    renderHeader()
    const link = screen.getByRole('link', { name: /Widget demo/i })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/widget-embed')
  })

  it('7.27 brand logo "F" is rendered inside the header', () => {
    renderHeader()
    expect(screen.getByText('F')).toBeInTheDocument()
  })
})
