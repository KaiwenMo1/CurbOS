import { useId, useRef } from 'react'
import type { useDiscovery } from './useDiscovery'

type Discovery = ReturnType<typeof useDiscovery>
type View = Discovery['view']

function message(view: View) {
  switch (view.kind) {
    case 'NOT_CONFIGURED': return 'Parking evidence not configured.'
    case 'LOADING': return 'Checking parking evidence…'
    case 'NO_PUBLIC_RELEASE': return 'No published parking evidence for this scope.'
    case 'WITHDRAWN': return 'Parking evidence was withdrawn.'
    case 'TIMEOUT': return 'Parking evidence request timed out.'
    case 'ERROR':
      if (view.code === 'SCOPE_UNKNOWN') return 'Configured parking scope is unknown.'
      if (view.code === 'RELEASE_CONTEXT_MISMATCH') return 'Parking release changed. Refresh parking evidence to continue.'
      if (view.code === 'INVALID_CURSOR') return 'The viewport page expired or became invalid. Refresh parking evidence.'
      if (view.code === 'RELEASE_NOT_FOUND') return 'The selected parking release is no longer accessible.'
      return 'Parking evidence temporarily unavailable.'
    default:
      if (view.bounded) return 'Viewport partially loaded. Zoom in to see more source segments.'
      switch (view.coverage) {
        case 'NO_VIEWPORT': return 'A basemap is needed to browse this release.'
        case 'ZOOM_IN': return 'Zoom in to an unwrapped viewport to load source evidence.'
        case 'OUTSIDE_REVIEWED_SCOPE': return 'Outside the reviewed parking scope.'
        case 'ASSESSED_NO_SOURCE_FEATURES': return 'No source segments in this assessed viewport.'
        case 'PARTIAL_SOURCE_COVERAGE':
          return view.features.length ? 'Partial source coverage.' : 'No source segments returned in this partially covered viewport.'
      }
  }
}

export function DiscoveryPanel({ discovery }: { discovery: Discovery }) {
  const { view, ready, selected, detail, select, retry, dismiss } = discovery
  const selector = useRef<HTMLSelectElement>(null)
  const detailID = useId()
  const detailHeading = useId()
  return (
    <section className="discovery-panel" aria-label="Parking evidence">
      <h2>Parking evidence</h2>
      <div className="discovery-status" role="status" aria-atomic="true">
        {view.kind === 'SYNTHETIC_TEST_DATA' && <strong>Synthetic test data</strong>}
        <p>{message(view)}</p>
      </div>
      {(view.kind === 'ERROR' || view.kind === 'TIMEOUT' || view.kind === 'WITHDRAWN' || view.kind === 'NO_PUBLIC_RELEASE') &&
        <button type="button" onClick={retry}>Refresh parking evidence</button>}
      {!!ready?.features.length && (
        <>
          <p className="evidence-legend"><span aria-hidden="true" />Source-reported curb segment — parking rules and availability not verified.</p>
          {ready.release.attribution.length > 0 && <p>Source attribution: {ready.release.attribution.join(' · ')}</p>}
          <label className="evidence-selector">
            Source segment
            <select ref={selector} value={selected?.id ?? ''} aria-controls={selected ? detailID : undefined}
              onChange={(event) => event.target.value ? select(event.target.value) : dismiss()}>
              <option value="">Choose a source segment</option>
              {ready.features.map((feature) => <option key={feature.id} value={feature.id}>{feature.id}</option>)}
            </select>
          </label>
        </>
      )}
      {selected && (
        <section id={detailID} className="evidence-detail" aria-labelledby={detailHeading}>
          <div className="evidence-detail-header">
            <h3 id={detailHeading}>Source segment details</h3>
            <button type="button" onClick={() => { dismiss(); selector.current?.focus() }}>Close details</button>
          </div>
          {!detail && <p role="status">Loading source details…</p>}
          {detail && 'error' in detail && <p role="status">
            {detail.error.kind === 'TIMEOUT' ? 'Source detail request timed out.' : 'Source details are unavailable.'}
          </p>}
          {detail && 'detail' in detail && (
            <>
              <dl>
                <dt>Publisher</dt><dd>{detail.detail.feature.properties.publisher}</dd>
                <dt>Source Zone ID</dt><dd>{detail.detail.feature.id}</dd>
                <dt>Source as of</dt><dd>{detail.detail.feature.properties.sourceAsOf ?? 'Unknown'}</dd>
                <dt>Geometry provenance</dt><dd>{detail.detail.feature.properties.geometryEvidence}</dd>
                <dt>Curb placement</dt><dd>{detail.detail.feature.properties.placement}</dd>
                <dt>Street side</dt><dd>{detail.detail.feature.properties.side}</dd>
                <dt>Road reference</dt><dd>{detail.detail.feature.properties.roadReference ?? 'Unknown'}</dd>
                <dt>Policy reference status</dt><dd>{detail.detail.feature.properties.policyStatus}</dd>
                <dt>Parking legality</dt><dd>{detail.detail.feature.properties.legality}</dd>
                <dt>Occupancy</dt><dd>{detail.detail.feature.properties.occupancy}</dd>
                <dt>Availability</dt><dd>{detail.detail.feature.properties.availability}</dd>
              </dl>
              {detail.detail.policies.length > 0 && <>
                <h4>Source Policy references</h4>
                <ul>{detail.detail.policies.map(({ id, position }) => <li key={`${id}:${position}`}>{id}</li>)}</ul>
              </>}
              {detail.detail.feature.properties.qaCodes.length > 0 && <>
                <h4>Source evidence warnings</h4>
                <ul>{detail.detail.feature.properties.qaCodes.map((code) => <li key={code}>{code}</li>)}</ul>
              </>}
            </>
          )}
        </section>
      )}
    </section>
  )
}
