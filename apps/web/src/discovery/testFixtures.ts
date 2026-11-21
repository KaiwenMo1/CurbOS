// Invented test records for Vitest and the isolated browser runner.
export const scope = 'synthetic-discovery-one'
export const uid = (number: number) => `00000000-0000-4000-8000-${String(number).padStart(12, '0')}`
export const a = uid(1001)
export const b = uid(1002)

export function release(id: string | null = a, version = 1, state?: 'WITHDRAWN') {
  return {
    scope,
    publication_state: id ? 'ACTIVE' : state ?? 'NO_PUBLIC_RELEASE',
    data_status: id ? 'SYNTHETIC_TEST_DATA' : state ?? 'NO_ACTIVE_RELEASE',
    release_id: id,
    pointer_version: id || state ? version : 0,
    is_current: !!id,
    public_eligible: false,
    activated_at: id ? '2026-01-01T00:00:00Z' : null,
    source_as_of: null,
    attribution: id ? ['CurbOS synthetic test fixtures'] : [],
    limitations: id ? ['DISCOVERY_ONLY', 'CURB_PLACEMENT_UNVERIFIED'] : [],
  }
}

export function feature(number = 1) {
  return {
    type: 'Feature',
    id: uid(number),
    geometry: { type: 'LineString', coordinates: [[-0.002, 0], [0.002, 0]] },
    properties: {
      source_zone_id: uid(number),
      publisher: 'synthetic-test',
      source_as_of: '2026-01-01T00:00:00Z',
      source_artifact_id: uid(1100),
      geometry_sha256: '1'.repeat(64),
      geometry_evidence: 'SOURCE_REPORTED',
      curb_placement: 'UNVERIFIED',
      street_side: 'LEFT',
      road_reference: 'fixture-road',
      policy_reference_status: 'RESOLVED_REFERENCES_ONLY',
      parking_legality: 'UNKNOWN',
      occupancy: 'UNKNOWN',
      availability: 'UNKNOWN',
      qa_codes: ['ZONE_GEOMETRY_REPEATED_VERTEX'],
      private_artifact_uri: 'private-artifact-sentinel',
    },
  }
}

export function page({
  id = a, version = 1, features = [feature()], cursor = null, coverage = 'PARTIAL_SOURCE_COVERAGE',
}: { id?: string; version?: number; features?: ReturnType<typeof feature>[]; cursor?: string | null; coverage?: string } = {}) {
  return {
    type: 'FeatureCollection',
    meta: { ...release(id, version), coverage_status: coverage, request_status: 'COMPLETE', exclusions: [] },
    features,
    links: { next_cursor: cursor },
  }
}

export function detail(number = 1, id = a, version = 1) {
  return {
    ...release(id, version),
    feature: feature(number),
    policy_references: [{ source_policy_id: uid(1200), source_position: 0, raw_policy: 'private-policy-sentinel' }],
    approved_by: 'private-reviewer-sentinel',
  }
}

export function json(data: unknown, status = 200, mime = 'application/json') {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': mime } })
}
