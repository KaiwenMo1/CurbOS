# CurbOS — Architecture Baseline v1.0

**Status:** Design baseline accepted for planning, not an implemented system  
**Date:** 2026-11-17  
**Scope:** Street-parking-first web platform for evidence-aware parking discovery, legality evaluation, and arrival-time decisions.  
**Companion:** `M0_DATA_FEASIBILITY_PLAN.md`.

## 1. Vision and scope

**Product statement:** CurbOS is an evidence-aware, street-parking-first geospatial platform to discover potential legal parking opportunities and help users assess convenience and uncertainty at arrival. It does not control autonomous vehicles or guarantee a space.

**Primary user journeys:** Going Home (residential/free/overnight) and Going Out (destination convenience, permitted metered parking, cost). Both share one search engine and differ in defaults.

**Core promises:**
- Distinguish *discovery* from *recommendations*; an unverified curb must never be presented as verified legal parking.
- Separate legal eligibility, physical fit, occupancy observations, prediction, cost, and routing confidence.
- Never convert missing information to positive evidence: UNKNOWN is not VACANT, FREE, FITS, or LEGAL.
- Do not conflate last-known sensor reading with real-time availability or guaranteed availability on arrival.
- Community experiences concern areas and parking-search difficulty; they are not exact-space vacancy observations.
- Simulation is isolated from production data and claims.
- Authoritative state lives in PostgreSQL; caches and client views are eventually consistent and reconciled.

**Out of initial scope:** comprehensive citywide free-residential legality; precise guaranteed free intervals without observations; ML ranking without real labels; vehicle control; reservations/payment; Kubernetes or multiple domain microservices.

## 2. Decision register — accepted ADRs

| ADR | Accepted decision |
|---|---|
| 001 | Modular Monolith + independent simulator |
| 002 | Hybrid Parking Resource Model |
| 003 | Hybrid real data plus isolated synthetic occupancy |
| 004 | Authoritative State + Eventually Consistent Delivery |
| 005 | Street spaces / flexible curb segments / facilities |
| 006 | Evidence-based legality, fit, occupancy, arrival prediction separated |
| 007 | Progressive verified data coverage |
| 008 | Street parking first (free residential and metered) |
| 009 | Going Home and Going Out use shared search engine |
| 010 | Evidence-aware ranking; do not invent uncertainty probabilities |
| 011 | Adaptive search radius |
| 012 | Evidence-tiered search results |
| 013 | Discovery separate from verified recommendations |
| 014 | Community-Sourced Parking Evidence, with review and provenance |
| 015 | Go core backend + Python ETL/simulator/ML |
| 016 | PostgreSQL/PostGIS, domain schemas, separate prod/sim DBs, pgx/sqlc, goose |
| 017 | PostgreSQL transactional inbox/outbox + Redis Streams and cache, staged rollout |
| 018 | MapLibre + OSRM, swappable traffic-aware routing adapter |
| 019 | React/TypeScript/Vite, MapLibre, TanStack Query, feature-based UI |
| 020 | Production-oriented medium complexity: Docker, CI, observability, tests, managed hosting |
| 021 | Monorepo + domain-oriented Go backend and feature-based frontend |
| 022 | Shared resource identity + specialized curb/space/facility tables |
| 023 | Use-case orchestration + domain ports/adapters, transaction-owned state |
| 024 | Source-aware ordering + conservative arbitration; conflict/unknown preservation |
| 025 | Utility-driven community contributions, experience-first feedback, no points/leaderboards |
| 026 | Explainable evidence-aware rankings; legal gate before recommendations |
| 027 | Contract-first REST + WebSocket, versioned events, snapshot reconciliation; private sessions default |

## 3. Logical runtime architecture

**Monorepo deployables:**
- `apps/web`: React map-first SPA.
- `backend/cmd/api`: Go HTTP and WebSocket gateway.
- `backend/cmd/worker`: Go inbox/stream processing and outbox relay, sharing domain packages but separate process.
- `data/pipelines`: Python source ingestion, spatial normalization, quality reports.
- `data/simulator`: scenario-based synthetic occupancy, *simulation environment only*.
- Supporting PostgreSQL/PostGIS, Redis, OSRM or routing provider, object storage (community evidence), deployment/observability.

**Logical application use cases:** SearchParking, GetMapViewport, GetResourceDetails, SubmitReport, ReviewEvidence, SaveParkingSession, CompleteParkingSession, SubmitParkingExperience, ApplyObservation, ImportDataBatch.

**Domain modules and ownership:**
- `geo`: resource IDs, block faces, curb zones, individual spaces, facilities, geometry versioning.
- `regulations`: rule validity, full stay interval, local timezone, permits, prices, exceptions.
- `occupancy`: observations, source-specific cursors, current effective state, freshness.
- `vehiclefit`: vehicle dimensions and known spatial intervals; cannot infer free gap from curb length.
- `routing`: batch driving/walking travel and provider-specific quality/traffic metadata.
- `prediction`: model versions and nullable outputs; no invented probabilities.
- `recommendation`: orchestration of eligibility gate and transparent ranking.
- `community`: submit/review reports, moderation, evidence provenance and approval decisions.
- `sessions`: private search/park session lifecycle, reminders, opt-in experience.
- `ingestion`: source adapters, validation, published import batches.
- `platform`: database adapters, auth, logging, messaging, config, external clients.

**Architectural boundaries:** Use cases orchestrate domain ports; infrastructure adapters implement them. Domain modules do not import Redis or OSRM SDKs. Avoid interfaces around pure functions. Data ownership applies to writes; cross-domain read projections may be coordinated by application layer.

## 4. Domain and relational model

Shared `geo.parking_resources` identity and typed `geo.curb_zones`, `geo.parking_spaces`, `geo.parking_facilities`. `geo.street_block_faces` model side-specific road segments. Parent/child curb vs metered-space overlap must not create duplicate recommendations. Resource IDs and geometry versions are distinct; downstream observations reference the geometry snapshot they concern.

Suggested domain schemas: `geo`, `rules`, `occupancy`, `community`, `sessions`, `sources`, `events`. Design and migrations are incremental rather than creating all tables in first PR.

- Geometry is not legality. Source-derived centerlines may be approximate; store precision and source history.
- Rules model definitions, targets, recurring local schedules, absolute exceptions, permit applicability and evidence. Evaluate **entire parking interval** at candidate-specific ETA and relevant timezone.
- Observations append history and preserve source identity/time; `current_state` is a derived *known* state with freshness and conflict metadata.
- Free curb intervals use along-curb offsets only with sufficiently precise observed geometry and measurements; no invented number of stalls.
- Community report/review evidence is distinct from occupancy authority. User-submitted rule photos do not automatically establish verified legality.
- `sessions.search_sessions` and `sessions.parking_sessions` are distinct. A private parked-location session never becomes a community observation without explicit opt-in.
- `sources.*` records provenance, licenses, import batch version and mapping external source IDs to stable internal IDs.

## 5. Search and API contracts

Contract-first OpenAPI `/v1`:
- `POST /v1/parking/search`: read-only structured request; Going Home/Going Out, origin/destination, DEPART_AT/ARRIVE_AT, stay duration/end, vehicle/permit and constraints.
- `GET /v1/parking/map`: viewport-based lightweight map geometries, coverage and non-personal detail.
- `GET /v1/parking/resources/{id}`: rules, source, observations, precision and versions.
- `GET /v1/parking/coverage`: actual verified spatial data coverage and age.
- `GET /v1/parking/updates`: WebSocket upgrade for versioned state-change notifications and scoped subscriptions (exact path/transport contract finalized before M6).
- Community reports and private parking-session REST endpoints follow role/ownership and opt-in rules.

Search: (1) validate/time semantics; (2) PostGIS candidate generation and static filters; (3) bounded batch route matrices and walking; (4) evaluate *complete* stay; (5) fit, effective observations, freshness; (6) optional calibrated prediction; (7) hard legal gate, ranking, reason codes; (8) recommendations and discovery as separate collections.

Responses explicitly encode `COMPLETE | PARTIAL | FAILED`, data coverage distinct from API execution, per-dimension UNKNOWN, nullable ETA/cost/prediction, `reason_codes`, source timestamps and versions. External routing failure must not yield fabricated ETA or legality. `Free only` means verified zero cost for requested stay, not missing pricing data.

## 6. Eventing and consistency

- External observations ingested into durable PostgreSQL inbox with scoped event deduplication.
- Dispatcher publishes IDs to Redis Streams with retries; duplicate dispatch is allowed and safe.
- Worker validates source sequence/epoch or reliable observation timestamps and geometry-version match; records history; conservatively arbitrates across sources; conditionally advances effective state.
- In one PostgreSQL transaction: consume/dedup record, effective state update + monotonic state version, and outbox write. ACK Redis only after commit.
- Durable outbox relay emits state-change notifications to Redis / WebSocket gateway. Reconnect/gaps trigger authoritative snapshot refresh; no guaranteed complete client event history.
- Pending Redis Streams are recovered; retries back off; invalid contracts quarantined, stale accepted historical observations do not overwrite newer states.
- Freshness is source-specific and not equivalent to accuracy; simulation environment has separate DB, Redis, permissions and cache namespace (prefer separate instance for production vs load tests).

## 7. Community engagement

Product is useful without crowdsourcing. Offer Save My Parking, reminders subject to rule confidence, optional one-tap *search duration* after parking, optional neighborhood/block-level impressions, and optional evidence sharing. No points/leaderboards in V1. Feedback includes failures (garage/gave up) to reduce success-only bias. Avoid prompts during driving, location tracing by default, or publishing exact habitual parking addresses. Privacy, deletion and explicit opt-in required.

## 8. Security and quality

One-command Docker Compose local, migrations, GitHub Actions checks, integration against real PostGIS/Redis, Go race tests, Python pytest/Ruff, TypeScript/Vitest/Playwright, k6 tests, structured logs + OpenTelemetry with optional Prometheus/Grafana. Encrypt connections, least-privilege prod/sim/database/service roles, protect uploads, explicit authz for private sessions, rate-limit expensive search/routes, backups and tested recovery.

**Non-negotiable invariants:** unknown ≠ available/free/legal/fit; full-stay legal evaluation; no unsupported precision; no synthetic data production contamination; no duplicate state application; late events cannot incorrectly roll back newer state; user report not sensor truth; production claims cite verifiable sources.

## 9. Release milestones (plan only)

M0 Data feasibility & architecture confirmation → M1 runnable monorepo/CI → M2 verified GIS map → M3 rules engine → M4 routing/search/recommendation → M5 eventing/simulation → M6 WebSocket live map → M7 private sessions/community evidence → M8 production hardening/benchmarks/public demo.

Each slice is runnable, tested and documented; do not build empty scaffold for the entire future architecture in the first PR. Actual throughput/latency targets are hypotheses until reproducibly benchmarked.

## 10. Explicit risks and unresolved details

1. **Critical:** completeness of authoritative *free residential curb* rules and geometry; M0 cannot assume full city coverage.
2. **High:** inferred curb geometry may be roadway centerline, without obstruction/driveway/hydrant or curb-side correctness.
3. **High:** occupancy feed is last-known rather than guaranteed fresh; investigate real observation distribution and join quality.
4. **High:** incomplete time-dependent regulation, overlapping sources, temporary bans and permit districts.
5. **Medium:** real occupancy prediction labels are sparse; do not market synthetic model results as real-world performance.
6. **Medium:** external routing quality, one-way access points, tile licensing and hosting/traffic cost.
7. **Medium:** community contributions opt-in rates and selection bias; measure rather than assume.
8. **Medium:** private user location/session security and image moderation.
9. **Decide at implementation:** codegen version, cloud vendor, auth system, object store, event retention, WebSocket auth/subscription details, reminder delivery and SLO values.

## 11. Source register (initial research, not exhaustive)

- LADOT inventory: https://data.lacity.org/d/s49e-q6j2
- LADOT last-known occupancy: https://data.lacity.org/d/e7h6-4a3e
- LADOT occupancy archive: https://data.lacity.org/d/cj8s-ivry
- StreetsLA sweeping: https://streets.lacity.gov/services/street-sweeping
- LADOT parking: https://ladot.lacity.gov/projects/parking-la
- LA GeoHub: https://geohub.lacity.org/
- LA Open Data terms: https://data.lacity.org/terms-of-use

Data page records and timestamps reflect publicly shown portal metadata as checked on 2026-11-17; do not equate them to a validated import or ground truth.
