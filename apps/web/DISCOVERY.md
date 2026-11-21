# Parking evidence in the web app

Configure `VITE_PARKING_SCOPE` in `apps/web/.env.local` only for an explicitly approved scope. The value is a public scope key. It is bundled at build time, so restart Vite or rebuild after changing it. An unset or invalid key displays **Parking evidence not configured** and sends no Discovery request. Configure an approved `VITE_MAP_STYLE_URL` separately to browse a viewport. The application never requests browser location. [Environment example](.env.example)

Vite forwards `/readyz` and `/v1/parking/` to the existing, restricted `CURBOS_DEV_API_ORIGIN`. For a deployed build, route those paths to Go on the same origin. The client uses the three existing release, map and Zone detail routes without cookies or redirect following. The ordinary Go API currently returns `NO_PUBLIC_RELEASE` for known scopes. The ordinary browser build accepts only the inactive publication states from the current contract. [Discovery API contract](../../contracts/openapi/discovery.yaml)

## Publication and viewport behavior

The map and source selector share a release-pinned snapshot. On initial load and after a settled change of viewport, the client checks current publication metadata, then requests pages for that exact scope, release and bounding box. Every page and detail response must match the selected release ID and pointer version. A changed viewport aborts requests and removes the previous evidence layer before MapLibre can paint replacement tiles. Switching trip modes preserves the map and its loaded evidence.

The client debounces viewport changes for 250 ms. A viewport must fit within the API's WGS84 ranges and 0.25° maximum span on each axis. At wider or wrapped bounds, the UI asks the user to zoom in. A single viewport load uses up to three pages of 100 features and retains at most 100,000 vertices. The UI labels an incomplete view if a cursor remains or if the vertex budget is reached. It also distinguishes an assessed viewport with zero projected source segments from partial coverage and a viewport outside the reviewed scope. These outcomes describe source evidence and imply no parking restriction or availability.

Metadata refreshes every 30 seconds after the previous check finishes. Requests have a six-second deadline per metadata, viewport, or detail operation. A timeout and an offline API have separate status messages. The app removes evidence and dismisses details when a refresh detects withdrawal, changed eligibility or an error. A withdrawn or mismatched pin and a rejected cursor clear the layer and trigger a metadata recheck. If the server still advertises the same rejected pin, the view stays closed until metadata changes or the user explicitly retries. A withdrawal can remain visible for the polling interval on an otherwise idle page before the next successful check observes it.

## Evidence and accessibility

The neutral line layer shows source LineStrings with their original coordinate values. Use the native **Source segment** selector to inspect the same evidence by keyboard. Attribution and the parking-data warning stay visible with source evidence. The panel labels placement `UNVERIFIED` and legality, occupancy and availability `UNKNOWN`. Source Policy references are identifiers only. The client projects a small set of public-safe fields and drops private URLs, payloads, and unrelated metadata.

## Test isolation and rollback

`npm --prefix apps/web run test -- --run` covers response validation, publication states, request cancellation, viewport limits, pagination, and MapLibre lifecycle with synthetic fixtures. `make e2e-test` first runs the ordinary build through Chromium, Vite, Go, and disposable PostGIS. A separate scratch build injects a test client and uses mocked Discovery responses to exercise the real MapLibre layer, withdrawal and keyboard detail. The ordinary entry point and preview expose no synthetic switch.

To suspend browser Discovery requests, unset `VITE_PARKING_SCOPE` and restart Vite or rebuild. To roll back the UI, restore the previous web build and development proxy configuration. The API and database migrations require no rollback for a frontend-only issue. Discovery budgets and the polling interval are initial implementation limits. Public geometry, rights approval, and field verification remain separate gates.
