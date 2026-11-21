import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { MapViewport } from './MapViewport'

const mockMap = vi.hoisted(() => ({
  start: vi.fn(),
  on: vi.fn(),
  off: vi.fn(),
  remove: vi.fn(),
  addControl: vi.fn(),
}))

vi.mock('maplibre-gl', () => ({
  Map: class {
    on = mockMap.on
    off = mockMap.off
    remove = mockMap.remove
    addControl = mockMap.addControl

    constructor(options: unknown) {
      mockMap.start(options)
    }
  },
  NavigationControl: class {},
  setWorkerUrl: vi.fn(),
}))

const styleURL = '/basemap/style.json'

function mapEvent(name: string, error = new Error('Basemap request failed')) {
  const call = mockMap.on.mock.calls.find(([event]) => event === name)
  if (!call) throw new Error(`MapLibre listener missing for ${name}`)
  act(() => call[1]({ error }))
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.stubEnv('VITE_PARKING_SCOPE', undefined)
  vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
})

afterEach(() => {
  cleanup()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('MapViewport', () => {
  it.each([
    undefined,
    ' ',
    '//maps.example.test/style.json',
    '/\\maps.example.test/style.json',
    'http://maps.example.test/style.json',
    'https:////maps.example.test/style.json',
    'https://user@maps.example.test/style.json',
    'https://',
  ])('keeps the map idle with an unset or unsupported style URL (%s)', async (style) => {
    render(<MapViewport styleURL={style} />)

    expect(screen.getByText('Basemap not configured')).toBeInTheDocument()
    await vi.dynamicImportSettled()
    expect(mockMap.start).not.toHaveBeenCalled()
  })

  it('announces renderer initialization failure and keeps the parking-data status', async () => {
    mockMap.start.mockImplementation(() => {
      throw new Error('WebGL2 unavailable')
    })
    vi.stubEnv('VITE_MAP_STYLE_URL', styleURL)
    render(<App />)

    expect(await screen.findByText('Map rendering unavailable')).toBeInTheDocument()
    expect(screen.getByText('No verified parking data available.')).toBeInTheDocument()
    expect(screen.queryByText('Basemap not configured')).not.toBeInTheDocument()
  })

  it('keeps a single map through Strict Mode and mode changes, then detaches listeners on unmount', async () => {
    vi.stubEnv('VITE_MAP_STYLE_URL', styleURL)
    const { unmount } = render(<StrictMode><App /></StrictMode>)

    await waitFor(() => expect(mockMap.start).toHaveBeenCalledTimes(1))
    expect(mockMap.start).toHaveBeenCalledWith(expect.objectContaining({
      style: new URL(styleURL, window.location.origin).href,
    }))
    const map = within(screen.getByRole('region', { name: 'Map viewport' }))
    const status = map.getByRole('status')
    expect(status).toHaveTextContent('Loading basemap')
    mapEvent('load')
    expect(map.getByRole('status')).toBe(status)
    expect(status).toBeEmptyDOMElement()

    fireEvent.click(screen.getByRole('radio', { name: 'Going Out' }))
    expect(mockMap.start).toHaveBeenCalledTimes(1)
    expect(mockMap.remove).not.toHaveBeenCalled()

    unmount()
    expect(mockMap.on).toHaveBeenCalledTimes(3)
    expect(mockMap.off.mock.calls).toEqual(mockMap.on.mock.calls)
    expect(mockMap.remove).toHaveBeenCalledTimes(1)
  })

  it('avoids constructing a map when unmounted before initialization', async () => {
    const { unmount } = render(<MapViewport styleURL={styleURL} />)
    unmount()

    await vi.dynamicImportSettled()
    expect(mockMap.start).not.toHaveBeenCalled()
    expect(mockMap.remove).not.toHaveBeenCalled()
  })

  it.each(['error', 'webglcontextlost'])('disposes the map and shows a fallback on %s', async (event) => {
    const { unmount } = render(<MapViewport styleURL={styleURL} />)
    await waitFor(() => expect(mockMap.start).toHaveBeenCalledTimes(1))
    if (event === 'webglcontextlost') mapEvent('load')

    mapEvent(event)

    expect(screen.getByRole('status')).toHaveTextContent('Map rendering unavailable')
    await waitFor(() => expect(mockMap.remove).toHaveBeenCalledTimes(1))
    expect(mockMap.off.mock.calls).toEqual(mockMap.on.mock.calls)
    unmount()
    expect(mockMap.remove).toHaveBeenCalledTimes(1)
  })

  it('keeps the loaded map through a tile error and disposes it on worker failure', async () => {
    render(<MapViewport styleURL={styleURL} />)
    await waitFor(() => expect(mockMap.start).toHaveBeenCalledTimes(1))
    mapEvent('load')
    mapEvent('error')
    expect(screen.getByRole('status')).toBeEmptyDOMElement()
    expect(mockMap.remove).not.toHaveBeenCalled()

    mapEvent('error', new Error('Worker failed to load. Check that the worker URL is correct.'))
    expect(screen.getByRole('status')).toHaveTextContent('Map rendering unavailable')
    await waitFor(() => expect(mockMap.remove).toHaveBeenCalledTimes(1))
  })

  it('creates a fresh map when mounted again after cleanup', async () => {
    const first = render(<MapViewport styleURL={styleURL} />)
    await waitFor(() => expect(mockMap.start).toHaveBeenCalledTimes(1))
    first.unmount()
    expect(mockMap.remove).toHaveBeenCalledTimes(1)

    const second = render(<MapViewport styleURL={styleURL} />)
    await waitFor(() => expect(mockMap.start).toHaveBeenCalledTimes(2))
    expect(screen.getByRole('status')).toHaveTextContent('Loading basemap')
    second.unmount()
    expect(mockMap.remove).toHaveBeenCalledTimes(2)
  })

  it('disposes the map if the initial style load never completes', async () => {
    vi.useFakeTimers()
    render(<MapViewport styleURL={styleURL} />)
    await act(() => vi.dynamicImportSettled())
    expect(mockMap.start).toHaveBeenCalledTimes(1)

    await act(() => vi.advanceTimersByTimeAsync(15_000))

    mapEvent('load')
    mapEvent('error')
    expect(screen.getByRole('status')).toHaveTextContent('Map rendering unavailable')
    expect(mockMap.remove).toHaveBeenCalledTimes(1)
  })
})
