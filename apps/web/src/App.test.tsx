import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

beforeEach(() => vi.stubEnv('VITE_MAP_STYLE_URL', undefined))

afterEach(() => {
  cleanup()
  vi.unstubAllEnvs()
})

describe('App', () => {
  it('shows the unconfigured basemap and makes the parking-data state explicit', () => {
    render(<App />)

    const map = screen.getByRole('region', { name: 'Map viewport' })
    expect(within(map).getByText('Basemap not configured')).toBeInTheDocument()
    expect(screen.getByText('No verified parking data available.')).toBeInTheDocument()
    expect(screen.queryByText('Map rendering unavailable')).not.toBeInTheDocument()
  })

  it('switches trip priorities while keeping the same map and parking-data state', () => {
    render(<App />)

    const map = screen.getByRole('region', { name: 'Map viewport' })
    const home = screen.getByRole('radio', { name: 'Going Home' })
    const out = screen.getByRole('radio', { name: 'Going Out' })
    expect(home).toBeChecked()
    expect(screen.getByText('Residential, free, and overnight street parking.')).toBeInTheDocument()

    fireEvent.click(out)
    expect(out).toBeChecked()
    expect(home).not.toBeChecked()
    expect(screen.getByText('Metered street parking, cost, and walking distance.'))
      .toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Map viewport' })).toBe(map)
    expect(screen.getByText('No verified parking data available.')).toBeInTheDocument()

    fireEvent.click(home)
    expect(home).toBeChecked()
  })
})
