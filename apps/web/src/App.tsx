import { useState } from 'react'
import { MapViewport } from './MapViewport'

const tripModes = [
  { id: 'home', label: 'Going Home', description: 'Residential, free, and overnight street parking.' },
  { id: 'out', label: 'Going Out', description: 'Metered street parking, cost, and walking distance.' },
] as const

function App() {
  const [mode, setMode] = useState<(typeof tripModes)[number]>(tripModes[0])

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="skip-link" href="#parking-controls">Skip to trip controls</a>
        <a className="wordmark" href="/" aria-label="CurbOS home">
          CurbOS
        </a>
      </header>

      <main className="workspace">
        <h1>Parking map</h1>
        <p className="data-status">No verified parking data available.</p>
        <div className="workspace-layout">
          <MapViewport styleURL={import.meta.env.VITE_MAP_STYLE_URL} />

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
                    {option.label}
                  </label>
                ))}
              </div>
              <p id="mode-description" aria-live="polite">{mode.description}</p>
            </fieldset>
          </section>
        </div>
      </main>
    </div>
  )
}

export default App
