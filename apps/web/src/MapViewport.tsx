import { useEffect, useRef, useState } from 'react'
import type { ErrorEvent as MapErrorEvent, Map as LibreMap } from 'maplibre-gl'
import workerURL from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url&no-inline'

const startupTimeoutMs = 15_000

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

function MapCanvas({ styleURL }: { styleURL: string }) {
  const container = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'unavailable'>('loading')

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
      activeMap.off('load', onLoad)
      activeMap.off('error', onError)
      activeMap.off('webglcontextlost', markUnavailable)
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
      if (stopped) return

      loaded = true
      window.clearTimeout(startupTimeout)
      setStatus('ready')
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
  }, [styleURL])

  return (
    <>
      <div className="map-canvas" ref={container} inert={status !== 'ready'} />
      <div className="map-message" role="status">
        {status === 'loading' && <p>Loading basemap…</p>}
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

export function MapViewport({ styleURL }: { styleURL?: string }) {
  const style = permittedStyleURL(styleURL)

  return (
    <section className="map-viewport" aria-label="Map viewport">
      {style ? (
        <MapCanvas key={style} styleURL={style} />
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
