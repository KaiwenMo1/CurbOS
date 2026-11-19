import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('App', () => {
  it('renders an explicit no-data state without parking claims', () => {
    render(<App />)

    expect(
      screen.getByRole('heading', {
        level: 1,
        name: 'No verified parking data available',
      }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/does not represent parking availability/i),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/no parking resources, sensor observations/i),
    ).toBeInTheDocument()
  })
})
