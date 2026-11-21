import { useState } from 'react'
import { BackendStatus } from './BackendStatus'
import { MapViewport } from './MapViewport'
import { configuredScope, createDiscoveryClient, viewportQuery, type Bounds, type DiscoveryClient, type Zone } from './discovery/client'
import { DiscoveryPanel } from './discovery/DiscoveryPanel'
import { useDiscovery } from './discovery/useDiscovery'

const tripModes = [
  { id: 'home', label: 'Going Home', description: 'Residential, free, and overnight street parking.' },
  { id: 'out', label: 'Going Out', description: 'Metered street parking, cost, and walking distance.' },
] as const

const publicClient = createDiscoveryClient()
const noFeatures: Zone[] = []

function App({ discoveryClient = publicClient }: { discoveryClient?: DiscoveryClient }) {
  const [mode, setMode] = useState<(typeof tripModes)[number]>(tripModes[0])
  const [viewport, setViewport] = useState({ bbox: 'NO_VIEWPORT', version: 0 })
  const scope = configuredScope(import.meta.env.VITE_PARKING_SCOPE)
  const discovery = useDiscovery(discoveryClient, scope, viewport)

  function updateBounds(bounds: Bounds | null) {
    const bbox = viewportQuery(bounds)
    setViewport((current) => current.bbox === bbox ? current : { bbox, version: current.version + 1 })
  }

  return (
    <div className="app-shell">
      <header className="site-header">
        <div className="site-header-inner">
          <a className="skip-link" href="#parking-controls">Skip to trip controls</a>
          <a className="wordmark" href="/" aria-label="CurbOS home">
            <span className="brand-mark" aria-hidden="true" />
            CurbOS
          </a>
          <p className="data-status" id="parking-data-status">
            <span aria-hidden="true" />
            No verified parking data available.
          </p>
        </div>
      </header>

      <main className="workspace" aria-describedby="parking-data-status">
        <div className="workspace-intro">
          <h1>Parking <span>map</span></h1>
        </div>
        <MapViewport styleURL={import.meta.env.VITE_MAP_STYLE_URL} evidence={scope ? {
          features: discovery.ready?.features ?? noFeatures, onBounds: updateBounds, onSelect: discovery.select,
        } : undefined} />

        <section
          className="control-panel"
          id="parking-controls"
          aria-label="Parking controls"
          tabIndex={-1}
        >
          <fieldset aria-describedby="mode-description">
            <legend>Trip mode</legend>
            <div className="mode-options">
              {tripModes.map((option) => (
                <label className="mode-option" key={option.id}>
                  <input
                    type="radio"
                    name="trip-mode"
                    value={option.id}
                    checked={option.id === mode.id}
                    onChange={() => setMode(option)}
                  />
                  <span className={`mode-symbol mode-symbol--${option.id}`} aria-hidden="true" />
                  <span className="mode-label">
                    {option.label}
                  </span>
                  <span className="mode-selection" aria-hidden="true" />
                </label>
              ))}
            </div>
            <p id="mode-description" aria-live="polite">{mode.description}</p>
          </fieldset>
          <DiscoveryPanel discovery={discovery} />
          <BackendStatus />
        </section>
      </main>
    </div>
  )
}

export default App
