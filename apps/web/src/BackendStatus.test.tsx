import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BackendStatus } from './BackendStatus'

const request = vi.fn<typeof fetch>()

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  request.mockReset()
  vi.stubGlobal('fetch', request)
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('BackendStatus', () => {
  it('checks the same-origin contract and only checks again on request', async () => {
    request
      .mockResolvedValueOnce(json(503, { status: 'not_ready' }))
      .mockResolvedValueOnce(json(200, { status: 'ready' }))
    render(<BackendStatus />)

    const checkAgain = screen.getByRole('button', { name: 'Check again' })
    expect(screen.getByRole('status')).toHaveTextContent('Checking backend…')
    expect(checkAgain).toHaveAttribute('aria-disabled', 'true')
    fireEvent.click(checkAgain)
    await screen.findByText('Backend unavailable')
    expect(screen.getByText('The backend could not verify the database.')).toBeInTheDocument()
    expect(request).toHaveBeenCalledTimes(1)
    expect(request).toHaveBeenCalledWith('/readyz', expect.objectContaining({
      cache: 'no-store',
      mode: 'same-origin',
      credentials: 'omit',
      redirect: 'error',
    }))

    fireEvent.click(checkAgain)
    await screen.findByText('Backend ready')
    expect(request).toHaveBeenCalledTimes(2)
  })

  it.each([
    () => new Response('', { status: 500 }),
    () => new Response('upstream details', { status: 502 }),
  ])('shows backend unavailable for a failed proxy', async (response) => {
    request.mockResolvedValue(response())
    render(<BackendStatus />)

    await screen.findByText('Backend unavailable')
    expect(screen.queryByText('upstream details')).not.toBeInTheDocument()
  })

  it.each([
    () => new Response('<!doctype html>', { headers: { 'Content-Type': 'text/html' } }),
    () => new Response('{', { headers: { 'Content-Type': 'application/json' } }),
    () => json(200, { status: 'ok' }),
    () => json(503, { status: 'ready' }),
    () => json(404, { status: 'not_found' }),
  ])('rejects unexpected readiness responses', async (response) => {
    request.mockResolvedValue(response())
    render(<BackendStatus />)

    await screen.findByText('Backend connection error')
    expect(screen.queryByText('Backend ready')).not.toBeInTheDocument()
  })

  it('shows a generic message for a rejected request', async () => {
    request.mockRejectedValue(new Error('private connection details'))
    render(<BackendStatus />)

    await screen.findByText('Backend connection error')
    expect(screen.queryByText('private connection details')).not.toBeInTheDocument()
  })

  it('aborts after the deadline and ignores a late result', async () => {
    vi.useFakeTimers()
    let resolve!: (response: Response) => void
    request.mockImplementation(() => new Promise((done) => { resolve = done }))
    render(<BackendStatus />)

    await act(() => vi.advanceTimersByTimeAsync(6_000))
    expect(request.mock.calls[0][1]?.signal?.aborted).toBe(true)
    expect(screen.getByRole('status')).toHaveTextContent('The readiness check timed out.')

    await act(async () => resolve(json(200, { status: 'ready' })))
    expect(screen.queryByText('Backend ready')).not.toBeInTheDocument()
  })

  it('aborts obsolete requests after Strict Mode replay and unmount', async () => {
    const replies: Array<(response: Response) => void> = []
    request.mockImplementation(() => new Promise((done) => { replies.push(done) }))
    const { unmount } = render(<StrictMode><BackendStatus /></StrictMode>)

    expect(request.mock.calls[0][1]?.signal?.aborted).toBe(true)
    await act(async () => replies[0](json(200, { status: 'ready' })))
    expect(screen.getByRole('status')).toHaveTextContent('Checking backend…')

    unmount()
    expect(request.mock.calls[1][1]?.signal?.aborted).toBe(true)
    await act(async () => replies[1](json(200, { status: 'ready' })))
  })
})
