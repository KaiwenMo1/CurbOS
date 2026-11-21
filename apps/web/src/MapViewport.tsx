import { useEffect, useEffectEvent, useLayoutEffect, useRef, useState } from 'react'
import type { ErrorEvent as MapErrorEvent, Map as LibreMap, MapLayerMouseEvent } from 'maplibre-gl'
import workerURL from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url&no-inline'
import type { Bounds, Zone } from './discovery/client'

const startupTimeoutMs = 15_000
const evidenceLayer = 'curbos-source-evidence'

function permittedStyleURL(value?: string) {
  const candidate = value?.trim()
  if (!candidate || /[\\\s]/.test(candidate)) return undefined

  try {
    const url = new URL(candidate, window.location.origin)
    const sameOriginPath = candidate.startsWith('/') && !candidate.startsWith('//') &&
      url.origin === window.location.origin
    const httpsURL = /^https:\/\/[^/]/i.test(candidate) && url.protocol === 'https:'
    if ((sameOriginPath || httpsURL) && !url.username && !url.password) {
      return url.href
    }
  } catch {
    return undefined
  }
}

type Evidence = {
  features: Zone[]
  onBounds(bounds: Bounds | null): void
  onSelect(id: string): void
}

function MapCanvas({ styleURL, evidence }: { styleURL: string; evidence?: Evidence }) {
  const container = useRef<HTMLDivElement>(null)
  const mapRef = useRef<LibreMap | undefined>(undefined)
  const [status, setStatus] = useState<'loading' | 'ready' | 'unavailable'>('loading')
  const [failedFeatures, setFailedFeatures] = useState<Zone[]>()
  const sourceVersion = useRef(0)
  const discoveryEnabled = Boolean(evidence)
  const features = evidence?.features
  const publishBounds = useEffectEvent((bounds: Bounds | null) => evidence?.onBounds(bounds))
  const selectFeature = useEffectEvent((id: string) => evidence?.onSelect(id))

  useLayoutEffect(() => {
    const map = mapRef.current
    if (!map || status !== 'ready' || !features?.length) return

    // Each view gets its own worker source. Remove the previous layer before
    // paint so MapLibre cannot substitute old tiles while the next source loads.
    const source = `${evidenceLayer}-${++sourceVersion.current}`
    let current = true
    let added = false
    try {
      map.addSource(source, { type: 'geojson', promoteId: 'source_zone_id', data: {
        type: 'FeatureCollection', features: features.map(({ type, id, geometry }) =>
          ({ type, geometry, properties: { source_zone_id: id } })),
      } })
      added = true
      map.addLayer({ id: evidenceLayer, source, type: 'line',
        layout: { 'line-cap': 'round' }, paint: { 'line-color': '#64728c', 'line-width': 4 },
      })
    } catch {
      queueMicrotask(() => { if (current) setFailedFeatures(features) })
    }
    return () => {
      current = false
      if (mapRef.current !== map || !added) return
      if (map.getLayer(evidenceLayer)) map.removeLayer(evidenceLayer)
      if (map.getSource(source)) map.removeSource(source)
    }
  }, [features, status])

  useEffect(() => {
    const element = container.current
    if (!element) return

    let stopped = false
    let loaded = false
    let map: LibreMap | undefined
    const startupTimeout = window.setTimeout(markUnavailable, startupTimeoutMs)

    function removeMap() {
      const activeMap = map
      if (!activeMap) return

      map = undefined
      mapRef.current = undefined
      activeMap.off('load', onLoad)
      activeMap.off('error', onError)
      activeMap.off('webglcontextlost', markUnavailable)
      if (discoveryEnabled && loaded) {
        activeMap.off('moveend', onBounds)
        activeMap.off('resize', onBounds)
        activeMap.off('click', evidenceLayer, onSelect)
        publishBounds(null)
      }
      activeMap.remove()
    }

    function markUnavailable() {
      if (stopped) return

      stopped = true
      window.clearTimeout(startupTimeout)
      setStatus('unavailable')
      // Let MapLibre finish dispatching the event before removing the map.
      queueMicrotask(removeMap)
    }

    function onLoad() {
      if (stopped || loaded || !map) return

      loaded = true
      window.clearTimeout(startupTimeout)
      if (discoveryEnabled) {
        try {
          if (map.getLayer(evidenceLayer)) throw new Error('Reserved evidence layer already exists')
          map.on('moveend', onBounds)
          map.on('resize', onBounds)
          map.on('click', evidenceLayer, onSelect)
          onBounds()
        } catch {
          markUnavailable()
          return
        }
      }
      mapRef.current = map
      setStatus('ready')
    }

    function onBounds() {
      const bounds = map?.getBounds()
      if (bounds) publishBounds([bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()])
    }

    function onSelect(event: MapLayerMouseEvent) {
      const id = event.features?.[0]?.id
      if (typeof id === 'string') selectFeature(id)
    }

    function onError({ error }: MapErrorEvent) {
      // MapLibre 6.19 reports worker failure through its generic map error event.
      if (!loaded || error.message.startsWith('Worker failed to load.')) markUnavailable()
    }

    async function startMap(target: HTMLDivElement) {
      try {
        const [{ Map, NavigationControl, setWorkerUrl }] = await Promise.all([
          import('maplibre-gl'),
          import('maplibre-gl/dist/maplibre-gl.css'),
        ])
        if (stopped) return

        // Vite serves the worker as a same-origin asset with its own build hash.
        setWorkerUrl(workerURL)
        map = new Map({
          container: target,
          style: styleURL,
          cooperativeGestures: true,
        })
        map.on('load', onLoad)
        map.on('error', onError)
        map.on('webglcontextlost', markUnavailable)
        map.addControl(new NavigationControl({ showCompass: false }))
      } catch {
        markUnavailable()
      }
    }

    void startMap(element)
    return () => {
      stopped = true
      window.clearTimeout(startupTimeout)
      removeMap()
    }
  }, [discoveryEnabled, styleURL])

  return (
    <>
      <div className="map-canvas" ref={container} inert={status !== 'ready'} />
      <div className="map-message" role="status">
        {status === 'loading' && <p>Loading basemap…</p>}
        {status === 'ready' && failedFeatures && failedFeatures === features && <p>Map evidence layer unavailable. Use the source segment selector.</p>}
        {status === 'unavailable' && (
          <>
            <span className="map-symbol" aria-hidden="true" />
            <p>Map rendering unavailable</p>
            <p>Check browser WebGL support and the configured map source, then reload.</p>
          </>
        )}
      </div>
    </>
  )
}

export function MapViewport({ styleURL, evidence }: { styleURL?: string; evidence?: Evidence }) {
  const style = permittedStyleURL(styleURL)

  return (
    <section className="map-viewport" aria-label="Map viewport">
      {style ? (
        <MapCanvas key={style} styleURL={style} evidence={evidence} />
      ) : (
        <div className="map-message">
          <span className="map-symbol" aria-hidden="true" />
          <p>Basemap not configured</p>
          <p>Set an approved map style to show streets.</p>
        </div>
      )}
    </section>
  )
}
