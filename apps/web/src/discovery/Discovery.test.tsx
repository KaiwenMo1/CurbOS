import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { createDiscoveryClient } from './client'
import { a, b, detail, feature, json, page, release, scope, uid } from './testFixtures'

const mockMap = vi.hoisted(() => ({
  start: vi.fn(), on: vi.fn(), off: vi.fn(), remove: vi.fn(),
  addSource: vi.fn(), addLayer: vi.fn(), removeLayer: vi.fn(), removeSource: vi.fn(),
  bounds: { getWest: (): number => 0, getSouth: (): number => 0, getEast: (): number => 0.1, getNorth: (): number => 0.1 },
}))

vi.mock('maplibre-gl', () => ({
  Map: class {
    on = mockMap.on
    off = mockMap.off
    remove = mockMap.remove
    addSource = mockMap.addSource
    addLayer = mockMap.addLayer
    removeLayer = mockMap.removeLayer
    removeSource = mockMap.removeSource
    getBounds() { return mockMap.bounds }
    getSource() { return mockMap.addSource.mock.calls.length ? {} : undefined }
    getLayer() { return mockMap.addLayer.mock.calls.length ? {} : undefined }
    addControl() {}

    constructor(options: unknown) { mockMap.start(options) }
  },
  NavigationControl: class {},
  setWorkerUrl: vi.fn(),
}))

const request = vi.fn<typeof fetch>()

function mockRoutes(handler: (url: URL, signal?: AbortSignal | null) => Response | Promise<Response>) {
  request.mockImplementation(async (input, options) => {
    const path = String(input)
    if (path === '/readyz') return json({ status: 'ready' })
    return handler(new URL(path, 'http://test.invalid'), options?.signal)
  })
}

function calls(path: string) {
  return request.mock.calls.filter(([url]) => String(url).startsWith(`/v1/parking/${path}`))
}

function mapEvent(event: string, value?: unknown) {
  const registered = mockMap.on.mock.calls.find(([name]) => name === event)
  if (!registered) throw new Error(`Missing listener ${event}`)
  act(() => registered.at(-1)(value))
}

async function launch({ synthetic = true, style = true, strict = false } = {}) {
  if (style) vi.stubEnv('VITE_MAP_STYLE_URL', '/basemap/style.json')
  const view = <App discoveryClient={synthetic ? createDiscoveryClient({ allowSynthetic: true }) : undefined} />
  const mounted = render(strict ? <StrictMode>{view}</StrictMode> : view)
  if (style) {
    await waitFor(() => expect(mockMap.start).toHaveBeenCalledTimes(1))
    mapEvent('load')
  }
  return mounted
}

function mapPage(data = page()) {
  return json(data, 200, 'application/geo+json')
}

function fail(status: number, code: string) {
  return json({ error: { code, message: 'private-server-sentinel' } }, status)
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.stubGlobal('fetch', request)
  vi.stubEnv('VITE_PARKING_SCOPE', scope)
  vi.stubEnv('VITE_MAP_STYLE_URL', undefined)
  mockMap.bounds.getWest = () => 0
  mockMap.bounds.getEast = () => 0.1
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('Discovery', () => {
  it.each([undefined, 'invalid scope'])('does not request a scope when configuration is %s', async (value) => {
    mockRoutes(() => { throw new Error('unexpected Discovery request') })
    vi.stubEnv('VITE_PARKING_SCOPE', value)
    render(<App />)
    expect(screen.getByText('Parking evidence not configured.')).toBeInTheDocument()
    expect(screen.getByText('Basemap not configured')).toBeInTheDocument()
    await act(() => new Promise((done) => setTimeout(done, 0)))
    expect(calls('')).toHaveLength(0)
  })

  it('shows a configured basemap and no publication without trying to load zones', async () => {
    mockRoutes(() => json(release(null)))
    await launch({ synthetic: false })
    expect(await screen.findByText('No published parking evidence for this scope.')).toBeInTheDocument()
    expect(screen.getByText('No verified parking data available.')).toBeInTheDocument()
    expect(calls('map')).toHaveLength(0)
    expect(calls('releases/current')[0]).toEqual([
      `/v1/parking/releases/current?scope=${scope}`,
      expect.objectContaining({ cache: 'no-store', mode: 'same-origin', redirect: 'error', credentials: 'omit' }),
    ])
    expect(mockMap.addLayer).not.toHaveBeenCalled()
  })

  it('keeps bounds and geometry idle without a configured basemap', async () => {
    mockRoutes(() => json(release()))
    await launch({ style: false })
    expect(await screen.findByText('A basemap is needed to browse this release.')).toBeInTheDocument()
    expect(screen.getByText('Basemap not configured')).toBeInTheDocument()
    expect(calls('map')).toHaveLength(0)
  })

  it('rejects synthetic data in an ordinary application even when the response is ACTIVE', async () => {
    mockRoutes(() => json(release()))
    await launch({ synthetic: false })
    expect(await screen.findByText('Parking evidence temporarily unavailable.')).toBeInTheDocument()
    expect(screen.queryByText('Synthetic test data')).not.toBeInTheDocument()
    expect(calls('map')).toHaveLength(0)
    expect(mockMap.addLayer).not.toHaveBeenCalled()
  })

  it('distinguishes withdrawal, an unknown scope and recovery without rendering transport errors', async () => {
    let reply = json(null, 503)
    mockRoutes(() => reply.clone())
    await launch({ style: false, synthetic: false })
    const refresh = () => fireEvent.click(screen.getByRole('button', { name: 'Refresh parking evidence' }))
    await screen.findByText('Parking evidence temporarily unavailable.')
    reply = fail(404, 'SCOPE_UNKNOWN')
    refresh()
    await screen.findByText('Configured parking scope is unknown.')
    expect(screen.queryByText('private-server-sentinel')).not.toBeInTheDocument()
    reply = json(release(null, 2, 'WITHDRAWN'))
    refresh()
    await screen.findByText('Parking evidence was withdrawn.')
    reply = json(release(null))
    refresh()
    await screen.findByText('No published parking evidence for this scope.')
  })

  it('times out a hung request and ignores a result after the abort', async () => {
    vi.useFakeTimers()
    let resolve: (res: Response) => void = () => {}
    mockRoutes(() => new Promise((done) => { resolve = done }))
    render(<App />)
    await act(() => vi.advanceTimersByTimeAsync(6_000))
    expect(screen.getByText('Parking evidence request timed out.')).toBeInTheDocument()
    expect(calls('releases/current')[0][1]?.signal?.aborted).toBe(true)
    await act(async () => resolve(json(release(null))))
    expect(screen.getByText('Parking evidence request timed out.')).toBeInTheDocument()
  })

  it('loads neutral lines through one map and inspects pinned evidence without leaking dropped fields', async () => {
    mockRoutes((url) => url.pathname.endsWith('/current') ? json(release()) :
      url.pathname.endsWith('/map') ? mapPage() : json(detail()))
    const { unmount } = await launch({ strict: true })
    const picker = await screen.findByRole('combobox', { name: 'Source segment' })
    expect(screen.getByText('Synthetic test data')).toBeInTheDocument()
    expect(screen.getByText(/Source-reported curb segment/)).toBeInTheDocument()
    expect(screen.getByText(/Source attribution/)).toHaveTextContent('CurbOS synthetic test fixtures')
    expect(mockMap.addLayer).toHaveBeenCalledWith(expect.objectContaining({
      id: 'curbos-source-evidence', type: 'line', paint: { 'line-color': '#64728c', 'line-width': 4 },
    }))
    expect(mockMap.addSource).toHaveBeenLastCalledWith('curbos-source-evidence-1', {
      type: 'geojson', promoteId: 'source_zone_id', data: { type: 'FeatureCollection',
        features: [{ type: 'Feature', geometry: feature().geometry, properties: { source_zone_id: uid(1) } }],
      },
    })
    fireEvent.change(picker, { target: { value: uid(1) } })
    const panel = await screen.findByRole('region', { name: 'Source segment details' })
    expect(await within(panel).findAllByText('UNKNOWN')).toHaveLength(3)
    expect(within(panel).getByText('SOURCE_REPORTED')).toBeInTheDocument()
    expect(within(panel).getByText('UNVERIFIED')).toBeInTheDocument()
    expect(within(panel).getByText(uid(1200))).toBeInTheDocument()
    expect(within(panel).getByText('ZONE_GEOMETRY_REPEATED_VERTEX')).toBeInTheDocument()
    expect(document.body.innerHTML).not.toContain('private-')
    const url = new URL(String(calls('zones/')[0][0]), 'http://test.invalid')
    expect(url.pathname).toBe(`/v1/parking/zones/${uid(1)}`)
    expect(url.searchParams.get('release_id')).toBe(a)
    const count = request.mock.calls.length
    fireEvent.click(screen.getByRole('radio', { name: 'Going Out' }))
    expect(request.mock.calls).toHaveLength(count)
    expect(mockMap.start).toHaveBeenCalledTimes(1)
    fireEvent.click(within(panel).getByRole('button', { name: 'Close details' }))
    expect(picker).toHaveFocus()
    unmount()
    expect(mockMap.on).toHaveBeenCalledTimes(6)
    expect(mockMap.off.mock.calls).toEqual(mockMap.on.mock.calls)
    expect(mockMap.remove).toHaveBeenCalledTimes(1)
  })

  it('does not fetch world bounds or trigger loops during repeated pan and zoom notifications', async () => {
    mockMap.bounds.getEast = () => 0.5
    mockRoutes((url) => url.pathname.endsWith('/current') ? json(release()) : mapPage())
    await launch()
    await screen.findByText(/Zoom in to an unwrapped viewport/)
    expect(calls('map')).toHaveLength(0)
    for (let i = 0; i < 12; i++) {
      mockMap.bounds.getEast = () => 0.1 + i / 1000
      mapEvent('moveend')
    }
    await screen.findByRole('combobox')
    expect(calls('map')).toHaveLength(1)
    for (let i = 0; i < 6; i++) {
      mapEvent('moveend')
      mapEvent('resize')
    }
    await act(() => new Promise((done) => setTimeout(done, 300)))
    expect(calls('map')).toHaveLength(1)
  })

  it('aborts a stale viewport and ignores late geometry from a former release', async () => {
    let second = false
    let finish: (res: Response) => void = () => {}
    mockRoutes((url) => {
      if (url.pathname.endsWith('/current')) return json(second ? release(b, 2) : release())
      return second ? mapPage(page({ id: b, version: 2, features: [feature(2)] })) :
        new Promise((done) => { finish = done })
    })
    await launch()
    await waitFor(() => expect(calls('map')).toHaveLength(1))
    second = true
    mockMap.bounds.getWest = () => -0.05
    mapEvent('moveend')
    expect(calls('map')[0][1]?.signal?.aborted).toBe(true)
    await screen.findByRole('option', { name: uid(2) })
    await act(async () => finish(mapPage()))
    expect(screen.queryByRole('option', { name: uid(1) })).not.toBeInTheDocument()
    expect(mockMap.addSource.mock.lastCall?.[1].data.features[0].properties.source_zone_id).toBe(uid(2))
  })

  it('clears geometry and details after a pinned detail reports withdrawal', async () => {
    let withdrawn = false
    mockRoutes((url) => {
      if (url.pathname.endsWith('/current')) return json(withdrawn ? release(null, 2, 'WITHDRAWN') : release())
      if (url.pathname.endsWith('/map')) return mapPage()
      withdrawn = true
      return fail(410, 'RELEASE_WITHDRAWN')
    })
    await launch()
    const picker = await screen.findByRole('combobox')
    fireEvent.change(picker, { target: { value: uid(1) } })
    await screen.findByText('Parking evidence was withdrawn.')
    expect(screen.queryByRole('region', { name: 'Source segment details' })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(mockMap.removeLayer).toHaveBeenLastCalledWith('curbos-source-evidence')
    expect(mockMap.removeSource).toHaveBeenLastCalledWith('curbos-source-evidence-1')
  })

  it('checks for withdrawal on a stationary viewport and removes the layer', async () => {
    vi.useFakeTimers()
    let withdrawn = false
    mockRoutes((url) => url.pathname.endsWith('/current') ?
      json(withdrawn ? release(null, 2, 'WITHDRAWN') : release()) : mapPage())
    vi.stubEnv('VITE_MAP_STYLE_URL', '/basemap/style.json')
    render(<App discoveryClient={createDiscoveryClient({ allowSynthetic: true })} />)
    await act(() => vi.dynamicImportSettled())
    mapEvent('load')
    await act(() => vi.advanceTimersByTimeAsync(250))
    expect(screen.getByRole('combobox')).toBeInTheDocument()
    await act(() => vi.advanceTimersByTimeAsync(30_000))
    expect(calls('map')).toHaveLength(1)
    withdrawn = true
    await act(() => vi.advanceTimersByTimeAsync(30_000))
    expect(screen.getByText('Parking evidence was withdrawn.')).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(mockMap.removeLayer).toHaveBeenCalledTimes(1)
  })

  it.each([
    [409, 'RELEASE_CONTEXT_MISMATCH', /Parking release changed/],
    [400, 'INVALID_CURSOR', /viewport page expired/],
  ] as const)('invalidates pages and rechecks once on %s instead of keeping a partial snapshot', async (status, code, message) => {
    mockRoutes((url) => {
      if (url.pathname.endsWith('/current')) return json(release())
      return url.searchParams.has('cursor') ? fail(status, code) : mapPage(page({ cursor: 'second-page' }))
    })
    await launch()
    await screen.findByText(message)
    await waitFor(() => expect(calls('releases/current').length).toBeGreaterThanOrEqual(2))
    expect(calls('map')).toHaveLength(2)
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(mockMap.addLayer).not.toHaveBeenCalled()
  })

  it('rejects mixed-release geometry before passing anything to MapLibre', async () => {
    mockRoutes((url) => (
      url.pathname.endsWith('/current') ? json(release()) : mapPage(page({ id: b, version: 2 }))
    ))
    await launch()
    await screen.findByText(/Parking release changed/)
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(mockMap.addLayer).not.toHaveBeenCalled()
  })

  it('rejects invalid positions and never paints the page', async () => {
    const malformed = feature()
    malformed.geometry.coordinates = [[0, 91], [0, 0]]
    mockRoutes((url) => url.pathname.endsWith('/current') ? json(release()) : mapPage(page({ features: [malformed] })))
    await launch()
    await screen.findByText('Parking evidence temporarily unavailable.')
    expect(mockMap.addSource).not.toHaveBeenCalled()
  })

  it('stops after three pinned pages and explicitly labels the partial view', async () => {
    let count = 0
    mockRoutes((url) => {
      if (url.pathname.endsWith('/current')) return json(release())
      count += 1
      expect(url.searchParams.get('release_id')).toBe(a)
      expect(url.searchParams.get('limit')).toBe('100')
      expect(url.searchParams.get('cursor')).toBe(count === 1 ? null : `cursor-${count - 1}`)
      return mapPage(page({ features: [feature(count)], cursor: `cursor-${count}` }))
    })
    await launch()
    await screen.findByText(/Viewport partially loaded/)
    expect(calls('map')).toHaveLength(3)
    expect(screen.getAllByRole('option')).toHaveLength(4)
  })

  it.each([
    ['OUTSIDE_REVIEWED_SCOPE', 'Outside the reviewed parking scope.'],
    ['ASSESSED_NO_SOURCE_FEATURES', 'No source segments in this assessed viewport.'],
  ])('shows %s independently of publication state', async (coverage, message) => {
    mockRoutes((url) => url.pathname.endsWith('/current') ? json(release()) : mapPage(page({ features: [], coverage })))
    await launch()
    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(screen.getByText('Synthetic test data')).toBeInTheDocument()
    expect(screen.getByText('No verified parking data available.')).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  })
})
