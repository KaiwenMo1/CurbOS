import type { Feature, LineString } from 'geojson'

export const maxPageSize = 100
export const maxPages = 3
export const requestTimeoutMs = 6_000

const scopePattern = /^[A-Za-z0-9_.-]{1,100}$/
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const digestPattern = /^[0-9a-f]{64}$/
const coverageStatuses = ['OUTSIDE_REVIEWED_SCOPE', 'ASSESSED_NO_SOURCE_FEATURES', 'PARTIAL_SOURCE_COVERAGE'] as const

export type Coverage = (typeof coverageStatuses)[number]
export type Bounds = readonly [west: number, south: number, east: number, north: number]
export type VisibleRelease = {
  kind: 'SYNTHETIC_TEST_DATA' | 'EVIDENCE_AVAILABLE'
  scope: string
  id: string
  version: number
  attribution: string[]
}
export type Publication = VisibleRelease | { kind: 'NO_PUBLIC_RELEASE' | 'WITHDRAWN' }
export type Zone = Feature<LineString, {
  publisher: string
  sourceAsOf: string | null
  geometryEvidence: 'SOURCE_REPORTED'
  placement: 'UNVERIFIED'
  side: 'LEFT' | 'RIGHT'
  roadReference: string | null
  policyStatus: 'RESOLVED_REFERENCES_ONLY'
  legality: 'UNKNOWN'
  occupancy: 'UNKNOWN'
  availability: 'UNKNOWN'
  qaCodes: string[]
}> & { id: string }
export type Page = { features: Zone[]; coverage: Coverage; nextCursor: string | null }
export type Detail = { feature: Zone; policies: { id: string; position: number }[] }

export interface DiscoveryClient {
  current(scope: string, signal: AbortSignal): Promise<Publication>
  page(release: VisibleRelease, bbox: string, cursor: string | null, signal: AbortSignal): Promise<Page>
  detail(release: VisibleRelease, id: string, signal: AbortSignal): Promise<Detail>
}

export class DiscoveryError extends Error {
  constructor(readonly code: string) {
    super(code)
  }
}

export function configuredScope(value: unknown) {
  return typeof value === 'string' && scopePattern.test(value) ? value : null
}

export function viewportQuery(bounds: Bounds | null) {
  if (!bounds) return 'NO_VIEWPORT'
  const [w, s, e, n] = bounds
  const rounded = bounds.map((value) => value.toFixed(6))
  const [west, south, east, north] = rounded.map(Number)
  if (!bounds.every(Number.isFinite) || w < -180 || e > 180 || s < -90 || n > 90 ||
    w >= e || s >= n || west >= east || south >= north || east - west > 0.25 || north - south > 0.25) {
    return 'ZOOM_IN'
  }
  return rounded.join(',')
}

function record(value: unknown): Record<string, unknown> {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>
  throw new DiscoveryError('INVALID_RESPONSE')
}

function uuid(value: unknown): value is string {
  return typeof value === 'string' && uuidPattern.test(value)
}

function integer(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

// Keep evidence labels short and plain. In particular, never render transport/storage URLs.
function label(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= 160 &&
    !/[<>:/\\@]/.test(value) && [...value].every((char) => char.charCodeAt(0) >= 32 && char.charCodeAt(0) !== 127)
}

function timestamp(value: unknown): value is string | null {
  return value === null || typeof value === 'string' &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    Number.isFinite(Date.parse(value))
}

function publication(value: unknown, scope: string, allowSynthetic: boolean): Publication {
  const r = record(value)
  const attribution = r.attribution
  if (r.scope !== scope || r.public_eligible !== false || !integer(r.pointer_version) ||
    typeof r.is_current !== 'boolean' || !timestamp(r.activated_at) || !timestamp(r.source_as_of) ||
    !Array.isArray(attribution) || attribution.length > 8 || !attribution.every(label) ||
    !Array.isArray(r.limitations) || !r.limitations.every(label)) {
    throw new DiscoveryError('INVALID_RESPONSE')
  }
  if (r.release_id === null && !r.is_current) {
    if (r.publication_state === 'NO_PUBLIC_RELEASE' && r.data_status === 'NO_ACTIVE_RELEASE') return { kind: 'NO_PUBLIC_RELEASE' }
    if (r.publication_state === 'WITHDRAWN' && r.data_status === 'WITHDRAWN') return { kind: 'WITHDRAWN' }
  }
  if (r.publication_state === 'ACTIVE' && r.data_status === 'SYNTHETIC_TEST_DATA' && uuid(r.release_id) && r.pointer_version > 0) {
    if (!allowSynthetic) throw new DiscoveryError('UNAUTHORIZED_EVIDENCE')
    return { kind: 'SYNTHETIC_TEST_DATA', id: r.release_id, scope, version: r.pointer_version, attribution }
  }
  // The approved PR-05 contract has no public ACTIVE response.
  throw new DiscoveryError('INVALID_RESPONSE')
}

function pinned(value: unknown, expected: VisibleRelease, allowSynthetic: boolean) {
  const got = publication(value, expected.scope, allowSynthetic)
  if (got.kind === 'WITHDRAWN') throw new DiscoveryError('RELEASE_WITHDRAWN')
  if (!('id' in got) || got.id !== expected.id || got.version !== expected.version || got.kind !== expected.kind) {
    throw new DiscoveryError('RELEASE_CONTEXT_MISMATCH')
  }
}

function zone(value: unknown): Zone {
  const f = record(value)
  const geometry = record(f.geometry)
  const p = record(f.properties)
  if (f.type !== 'Feature' || !uuid(f.id) || p.source_zone_id !== f.id ||
    geometry.type !== 'LineString' || !Array.isArray(geometry.coordinates) ||
    geometry.coordinates.length < 2 || geometry.coordinates.length > 10_000 ||
    !label(p.publisher) || !timestamp(p.source_as_of) || !uuid(p.source_artifact_id) ||
    typeof p.geometry_sha256 !== 'string' || !digestPattern.test(p.geometry_sha256) ||
    (p.street_side !== 'LEFT' && p.street_side !== 'RIGHT') ||
    (p.road_reference !== null && !label(p.road_reference)) ||
    p.geometry_evidence !== 'SOURCE_REPORTED' || p.curb_placement !== 'UNVERIFIED' ||
    p.policy_reference_status !== 'RESOLVED_REFERENCES_ONLY' || p.parking_legality !== 'UNKNOWN' ||
    p.occupancy !== 'UNKNOWN' || p.availability !== 'UNKNOWN' ||
    !Array.isArray(p.qa_codes) || p.qa_codes.length > 32 || !p.qa_codes.every(label)) {
    throw new DiscoveryError('INVALID_RESPONSE')
  }
  const coordinates = geometry.coordinates.map((point: unknown) => {
    if (!Array.isArray(point) || point.length !== 2 || !point.every(Number.isFinite) ||
      Math.abs(point[0]) > 180 || Math.abs(point[1]) > 90) throw new DiscoveryError('INVALID_RESPONSE')
    return [point[0], point[1]] as [number, number]
  })
  return { type: 'Feature', id: f.id, geometry: { type: 'LineString', coordinates }, properties: {
    publisher: p.publisher, sourceAsOf: p.source_as_of, geometryEvidence: p.geometry_evidence,
    placement: p.curb_placement, side: p.street_side, roadReference: p.road_reference,
    policyStatus: p.policy_reference_status, legality: p.parking_legality, occupancy: p.occupancy,
    availability: p.availability, qaCodes: p.qa_codes,
  } }
}

const apiErrors = new Map([
  [400, ['INVALID_CURSOR', 'INVALID_BBOX', 'VIEWPORT_TOO_LARGE']],
  [404, ['SCOPE_UNKNOWN', 'RELEASE_NOT_FOUND', 'FEATURE_NOT_PUBLISHED']],
  [409, ['RELEASE_CONTEXT_MISMATCH']],
  [410, ['RELEASE_WITHDRAWN']],
])

async function receive(path: string, params: URLSearchParams, mime: string, signal: AbortSignal) {
  const response = await fetch(`/v1/parking/${path}?${params}`, {
    signal, cache: 'no-store', mode: 'same-origin', credentials: 'omit', redirect: 'error',
    headers: { Accept: mime },
  })
  const contentType = response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase()
  if (response.status !== 200) {
    const codes = apiErrors.get(response.status)
    if (codes && contentType === 'application/json') {
      const body = await response.json().catch(() => null) as { error?: { code?: string } } | null
      const code = body?.error?.code
      if (code && codes.includes(code)) throw new DiscoveryError(code)
    }
    throw new DiscoveryError('API_UNAVAILABLE')
  }
  if (contentType !== mime) throw new DiscoveryError('INVALID_RESPONSE')
  return record(await response.json())
}

// Only the isolated test entry injects a client configured to accept synthetic evidence.
export function createDiscoveryClient({ allowSynthetic = false } = {}): DiscoveryClient {
  return {
    async current(scope, signal) {
      const value = await receive('releases/current', new URLSearchParams({ scope }), 'application/json', signal)
      const release = publication(value, scope, allowSynthetic)
      if ('id' in release && value.is_current !== true) throw new DiscoveryError('INVALID_RESPONSE')
      return release
    },
    async page(release, bbox, cursor, signal) {
      const params = new URLSearchParams({ scope: release.scope, release_id: release.id, bbox, limit: String(maxPageSize) })
      if (cursor) params.set('cursor', cursor)
      const value = await receive('map', params, 'application/geo+json', signal)
      pinned(value.meta, release, allowSynthetic)
      const meta = record(value.meta)
      const links = record(value.links)
      const coverage = coverageStatuses.find((status) => status === meta.coverage_status)
      const nextCursor = links.next_cursor
      if (value.type !== 'FeatureCollection' || !Array.isArray(value.features) ||
        value.features.length > maxPageSize || !coverage || meta.request_status !== 'COMPLETE' ||
        (nextCursor !== null && (typeof nextCursor !== 'string' || !/^[A-Za-z0-9_.-]{1,1024}$/.test(nextCursor))) ||
        (coverage !== 'PARTIAL_SOURCE_COVERAGE' && (value.features.length !== 0 || nextCursor !== null)) ||
        (nextCursor !== null && value.features.length === 0)) throw new DiscoveryError('INVALID_RESPONSE')
      return { features: value.features.map(zone), coverage, nextCursor }
    },
    async detail(release, id, signal) {
      if (!uuid(id)) throw new DiscoveryError('INVALID_RESPONSE')
      const params = new URLSearchParams({ scope: release.scope, release_id: release.id })
      const value = await receive(`zones/${id}`, params, 'application/json', signal)
      pinned(value, release, allowSynthetic)
      const feature = zone(value.feature)
      if (feature.id !== id || !Array.isArray(value.policy_references) ||
        value.policy_references.length > 250) throw new DiscoveryError('INVALID_RESPONSE')
      const policies = value.policy_references.map((item: unknown) => {
        const p = record(item)
        if (!uuid(p.source_policy_id) || !integer(p.source_position)) throw new DiscoveryError('INVALID_RESPONSE')
        return { id: p.source_policy_id, position: p.source_position }
      })
      return { feature, policies }
    },
  }
}
