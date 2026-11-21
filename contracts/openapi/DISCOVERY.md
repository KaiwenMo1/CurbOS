# M2 Discovery API

PR-05 implements the three approved Master Pack routes. All responses use `Cache-Control: no-store`. Requests require an explicit scope. The ordinary API reports `NO_PUBLIC_RELEASE` with `data_status=NO_ACTIVE_RELEASE` for a known scope and masks synthetic pointer metadata. Unknown scopes return `404 SCOPE_UNKNOWN`. [OpenAPI contract and synthetic examples](discovery.yaml)

| GET route | Parameters and result |
|---|---|
| `/v1/parking/releases/current` | `scope`. Returns the current eligible release or an explicit publication state. |
| `/v1/parking/map` | `scope` and `bbox` in west, south, east, north order, with optional `release_id`, `limit`, and `cursor`. Returns GeoJSON using source LineStrings in WGS84 longitude/latitude order. |
| `/v1/parking/zones/{source_zone_id}` | `scope` and required `release_id`. Returns an exact release-scoped Zone and ordered source Policy references. |

Bounding boxes must be finite, ordered, inside the longitude and latitude ranges and at most 0.25° on each axis. Antimeridian wrapping is unsupported. Limits run from 1 to 250 with a default of 100. These are initial engineering bounds with no measured production throughput claim. The indexed PostGIS predicate selects original lines intersecting the bbox. A line may extend beyond the viewport and stays within the independently reviewed publication boundary.

## Evidence and coverage

- `SYNTHETIC_TEST_DATA` identifies isolated test responses. `public_eligible=false` applies to every response in this slice.
- `SOURCE_REPORTED` describes the geometry's provenance. `curb_placement=UNVERIFIED` describes the absence of independent curb placement evidence. Source UUIDs and artifact UUIDs identify evidence. They do not identify physical parking resources.
- `RESOLVED_REFERENCES_ONLY` describes same-release Policy pointers. Parking legality, occupancy and availability are each `UNKNOWN`. The response carries no parking capacity estimate, raw source URL, raw Policy payload, or private QA or reviewer records.
- `OUTSIDE_REVIEWED_SCOPE` identifies a disjoint viewport. `ASSESSED_NO_SOURCE_FEATURES` identifies a viewport wholly inside the reviewed boundary with zero matching projected lines. `PARTIAL_SOURCE_COVERAGE` covers intersecting viewports with features or only partial intersection. These labels describe source evidence. They make no assertion about parking or the completeness of legal restrictions.
- `NO_PUBLIC_RELEASE` indicates no eligible release. `WITHDRAWN` carries `NOT_ASSESSED` map coverage. Exclusion counts have a null value and `NOT_COMPUTED` status because a global exclusion total cannot establish a viewport count.

## Pins, errors and recovery

The synthetic read uses one PostgreSQL statement. A read-only `STABLE` function selects one release and uses the statement snapshot for every eligibility check, Zone, Policy and artifact lookup. A concurrent pointer change affects new requests. Explicit pins stay on a previously active release while its frozen snapshot remains eligible. `is_current` compares the pin to the scope pointer at read time. For a historical pin, `pointer_version` identifies the latest activation of that release visible to the request. [PostgreSQL function snapshots](https://www.postgresql.org/docs/17/xfunc-volatility.html)

Pages follow the source Zone UUID in ascending byte order. The signed cursor binds scope, release and bbox and expires 15 minutes after the first page. Repeat the same filters and pass `links.next_cursor` to continue. The test server uses a process-local key. A restart invalidates its cursors.

- Invalid or duplicate inputs give `400`. Unpinned detail gives `400 RELEASE_PIN_REQUIRED`.
- Invalid, expired or tampered cursors give `400 INVALID_CURSOR`. A cursor for a different scope, release or bbox gives `409 RELEASE_CONTEXT_MISMATCH`.
- Missing, never-activated, ineligible or cross-scope release pins give `404 RELEASE_NOT_FOUND`. An unpublished Zone gives `404 FEATURE_NOT_PUBLISHED`.
- Explicit withdrawal or rights revocation gives `410 RELEASE_WITHDRAWN` for the affected pin. Retry from the current-release endpoint to start a new view. Product rollback advances the existing pointer via PR-04, and a subsequent unpinned request sees the rollback target.
- Database outage, deadline or unavailable Discovery schema gives a sanitized, retryable `503 DISCOVERY_UNAVAILABLE`. Health and readiness retain their M1 contract.

## Runtime credentials

Apply Goose through `00005`. Provision a separate login with membership only in `curbos_api_reader`, then point `CURBOS_DATABASE_URL` to that login and inject its password through your normal secret mechanism. This role can check scope existence and read the Goose columns used for readiness. The migration creates NOLOGIN capability roles and provisions no passwords or memberships. The disposable Go integration test alone constructs the synthetic HTTP handler with a separately authenticated `curbos_api_synthetic_reader` login. The production binary offers no synthetic switch.

Use `make api-test` for the disposable integration suite. It seeds invented evidence through the PR-04 database lifecycle and verifies concurrent activation while an HTTP read is blocked on a database lock. The existing CDS tests exercise file-backed verification independently. During a code rollback, restore the previous API first. Migration `00005` Down removes its functions, API privileges and indexes while preserving publication evidence. Run schema Down only in an appropriate controlled database context. Production publication and its authorization remain a separate gate.
