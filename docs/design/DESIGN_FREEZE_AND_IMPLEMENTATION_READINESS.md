# CurbOS — Design Freeze & Coding Readiness Review (proposal, not accepted ADR)

**Updated:** 2026-11-18  
**Purpose:** Decide what remains to settle before asking Codex to implement a public-facing parking search. No production application code is included.

## 1. Already decided; do not reopen by default
- ADR-001–027 remain accepted. Source of truth: `../core/CURBOS_HANDOFF_AND_M0_07_2026-11-18.md`.
- Users receive honest **recommendations vs discovery**. ALLOWED is conditional on complete-stay legality evidence for a specified vehicle/time, not a universal legal guarantee.
- Backend Go modular monolith, PostGIS, Redis inbox/outbox/streams, MapLibre + OSRM, React, contract-first REST + **WebSocket** with versioned snapshot reconciliation, isolated simulator.
- Utility-driven, experience-first, opt-in community contribution; default private sessions, no gamification.

## 2. Proposed design-freeze boundaries

### 2.1 Data ingestion / import publication (important before M2)
**Raw snapshots are immutable.** Save source URI, fetch time, source as-of time, SHA-256, license/attribution, spatial scope, source CRS/coordinate precision and parser version.

**Staging before publication.** Parse and validate into a staging batch; never mutate published geometries/rules record-by-record as partial files stream in. Validate uniqueness, referential completeness, geometry sanity, policy schema variability and dataset-specific semantics, then *publish* a coherent version or reject it.

**No inference of legality from null.** `rate=0`, `undesignated`, no matched zone, no red-curb feature and no PPD feature do not establish a free, legal curb. Original CDS policy `priority` and overlapping time spans require verified source semantics; do not silently treat maximum numeric priority as globally dispositive.

**Stable identity ≠ static geometry.** External provider IDs map to stable internal IDs in a source-scoped mapping. A new import updates geometry version; observations tied to old geometry must be reassessed or quarantined if the spatial meaning changes.

**No invented curb capacity.** A block-face road centerline is not a curb and a curb length divided by vehicle length is not observed vacancy.

### 2.2 Search snapshot consistency (important before M4)
Each search response includes evaluated `data_batch_version`, effective `rules_version`, `generated_at`, `coverage_summary` and known partial failures. Returning a mixed version of newly imported geometry with old rules must be prevented via published batch boundaries or versioned cross-links. A map user may see a newer observation than the old search; show snapshot timestamp and re-evaluate affected ranking.

**Eligibility is interval-based**, includes candidate-specific arrival, timezone/DST, permit, price, full planned stay, exceptions and verified coverage. Route-provider ETA is a point estimate, not an occupancy guarantee. Allow user-requested *discovery* when ETA cannot be established, but never assert arrival-dependent legality without enough time evidence.

### 2.3 Live WebSocket API (important before M6)
REST remains authoritative. WS notifications are scoped by explicit viewport/resource subscriptions, include `resource_id`, monotonic `state_version`, published version and event metadata. A notification is a hint/invalidation, not guaranteed full event history. Enforce subscription limits and backpressure; avoid exact user parking positions in public topics. Reconnect and detected gaps force REST snapshot refresh. Authz for private session channels must be separate from public curb updates.

### 2.4 Parking session/privacy (important before M7)
A private Save My Parking session does not by itself imply occupant truth or public sharing. Search feedback refers to area-level search difficulty, not exact empty-space location. Distinguish `COMPLETED` from `EXPIRED_UNCONFIRMED`; never infer leaving from timer expiry. Define access control, consent, deletion, notification delivery semantics and data retention before shipping session features.

## 3. Proposed engineering guardrails
- One vertical-slice PR at a time, runnable end to end, no speculative interfaces/services.
- Real dataset tests assert provenance and unknown handling; synthetic fixtures are clearly named and run in isolated tests.
- All schema changes through goose; no manual production edits; pgx/sqlc query generation reproducible.
- Tests must include failed/missing policy linkage, contradictory overlapping rules, midnight/DST, duplicate source events, out-of-order delivery, changing geometry and websocket snapshot recovery.
- Security for API tokens, source uploads, coordinates, authz and rate-limits; never log residential search/parking position by default.
- Claim no p95, throughput, deployment success, model accuracy or legal coverage without reproducible real measurements.

## 4. Design-review decisions still to approve (implementation choices, not new ADRs)
| Topic | Proposed default | Must be decided before |
|---|---|---|
| Batch publication | Immutable raw + staging + atomic published version | M2 |
| Initial pilot | DTLA for CDS *data validation*, Westwood comparison; choose product pilot only after audit | M2/M3 |
| Verified legal threshold | Evidence-completeness checklist per requested stay, no blanket rule-by-absence | M3 |
| Search API version fields | `source_snapshot_id`, `rules_version`, `as_of`, `coverage`, partial failures | M4 |
| Live delivery policy | Versioned WS invalidation + REST snapshots, bounded subscriptions | M6 |
| Reminder transport | In-app first; external delivery only when consent & infrastructure verified | M7 |
| Cloud vendor | Defer until deployment needs and cost measured | M8 |

## 5. Coding-file sequence (planning only; NOT generated yet)
**Stage A — Planning artifacts:** `AGENTS.md`, `docs/adr/INDEX.md`, `docs/data-sources/SOURCE_CATALOG.md`, `docs/architecture/DECISION_REGISTER.md`, `docs/milestones/M0_M1_ACCEPTANCE.md`.

**Stage B — M0 Codex-safe audit tasks:** run two existing auditors on actual downloaded official files and attach full checksums, join-denominators, source freshness histograms and sample failures; do not turn them into production ETL yet.

**Stage C — M1 starter implementation:** `compose.yaml` (PostGIS, Go, React), minimum `/healthz` HTTP, Vite MapLibre shell, goose migrations baseline, CI and one API/UI integration test. Do **not** build Redis/ML/WS in M1.

**Stage D — M2 vertical slice:** staged CDS import, PostGIS resources, `GET /v1/parking/map`, source/coverage metadata, map UI. No legal recommendation until evidence gates pass.

## 6. Readiness gate
- Architecture: **READY FOR PLANNING** (27 decisions accepted).
- Coding scaffolding: **CAN START WITH USER APPROVAL** (M1 does not make parking-legality claims).
- Verified public recommendations: **NOT READY** (complete DTLA zone-policy audit, trusted rules and 20 block faces remain open).
- User can start foundational coding and empirical research in parallel, but must not advertise verified legal parking before evidence verification.

## 7. Proposed next design decision
Accept **immutable source snapshot → validated staging batch → atomic published version** as the first ingestion correctness contract. Then finalize M1's exact initial files and acceptance tests before asking Codex to write code.
