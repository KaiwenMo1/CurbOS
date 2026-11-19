function App() {
  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="wordmark" href="/" aria-label="CurbOS home">
          CurbOS
        </a>
        <span className="milestone">M1 · Repository foundation</span>
      </header>

      <main className="empty-state">
        <p className="eyebrow">Foundation status</p>
        <h1>No verified parking data available</h1>
        <p className="summary">
          CurbOS is establishing its trusted data foundation. This page does not
          represent parking availability, legality, price, or vehicle fit.
        </p>

        <section className="scope-card" aria-labelledby="scope-heading">
          <h2 id="scope-heading">What this build includes</h2>
          <ul>
            <li>A testable React and TypeScript application shell</li>
            <li>No parking resources, sensor observations, or legal claims</li>
            <li>No location collection, map tiles, or external telemetry</li>
          </ul>
        </section>
      </main>

      <footer>PR-01 · Honest empty state</footer>
    </div>
  )
}

export default App
