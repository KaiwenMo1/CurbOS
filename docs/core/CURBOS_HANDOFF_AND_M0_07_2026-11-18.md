# CurbOS — Persistent Project Handoff + M0-07 Audit Decision

**Updated:** 2026-11-18  
**Status:** Architecture decisions accepted (ADR-001–027); research and data feasibility in progress; production implementation **not started**.  
**Purpose:** Bring this file to any new ChatGPT/Codex conversation together with original architecture/feasibility documents, so that agreed requirements are not lost. This is a snapshot of decisions, **not a claim of permanent assistant memory**.

## A. Product contract: what CurbOS is (and is not)

- **Street-parking-first map app**, with **Going Home** (overnight/free residential preference) and **Going Out** (destination/short-stay convenience) sharing one search engine.
- Supports curb zones (including undelineated curb), marked spaces, and secondary parking facilities; don't count a curb zone and its child spaces twice.
- Search factors: intended start/arrival time, **full planned stay**, vehicle fit, permit, rules, pricing, origin/destination route ETA, walking time, occupancy observations, and optionally validated predictions.
- **Recommendations vs Discovery are distinct**: missing or conflicting legal coverage belongs in Discovery, never as verified-legal recommendation.
- **UNKNOWN is not VACANT, FREE, FITS, or LEGAL.** A vacant sensor reading is not a guaranteed vacancy on arrival. A long curb is not a count of vehicle-sized gaps. No unsupported confidence percentage.
- **Community design is utility-driven, not gamified**: save parking privately, reminders, post-parking one-tap *parking search duration*, optional area congestion feedback, optional departure/report consent; no points/leaderboards. Users generally cannot report exact open curb positions. User feedback is NOT authoritative occupancy.
- Private parking session and search session are distinct. Do not expose private residence/location history or silently convert sessions to community reports.
- **Real government sources and isolated simulation** for engineering tests, never merged or presented as measured real-world accuracy. No autonomous-car control, checkout/reservation, or premature ML hype.

## B. Confirmed ADR decisions (do not silently change)

| ID | Decision |
|---|---|
| 001 | Modular Go monolith + independent simulator |
| 002 | Hybrid parking resources |
| 003 | Real data + strictly isolated synthetic data |
| 004 | PostgreSQL authority + eventually consistent clients/cache |
| 005 | Marked spaces, flexible curb zones, parking facilities |
| 006 | Separate legality / fit / observed occupancy / predictions / evidence |
| 007 | Progressive verified coverage |
| 008 | Street parking first, esp. free residential and metered |
| 009 | Going Home & Going Out share search logic |
| 010 | Evidence-aware ranking and UNKNOWN |
| 011 | Adaptive search radius |
| 012 | Evidence tiers in results |
| 013 | Discovery separate from verified recommendations |
| 014 | Community evidence with provenance, moderation and review |
| 015 | Go core backend + Python GIS ETL, simulator, future ML |
| 016 | PostgreSQL/PostGIS, pgx/sqlc, goose; domain schemas; isolated prod/sim DB and credentials |
| 017 | PostgreSQL transactional Inbox/Outbox + Redis Streams + Redis cache; at-least-once & idempotency |
| 018 | MapLibre + OSRM drive/walk, replaceable RoutingProvider |
| 019 | React/TS/Vite + MapLibre + TanStack Query, responsive map-first UI |
| 020 | Medium-complexity production quality: Compose, CI, OTel, measured perf, no initial K8s |
| 021 | Monorepo, domain modules and vertical slices |
| 022 | Shared resource UUID plus specialist subtype tables and geometry/version evidence |
| 023 | Use Case Orchestration + Domain Ports/Adapters, PostgreSQL atomic state writes |
| 024 | Source-aware ordering, freshness, conservative arbitration, conflict/unknown preservation |
| 025 | Utility-driven, experience-first opt-in contributions; no points or gamification |
| 026 | Explainable ranking: eligibility gate, hard constraints then soft preferences; reason codes |
| 027 | Contract-first REST + **WebSocket** (NOT SSE) + versioned updates + snapshot reconciliation; private sessions default |

All 27 are ACCEPTED; don't reopen a decision without a concrete new incompatibility and user approval.

## C. Implementation topology and invariants

- Monorepo: `apps/web`, `backend/cmd/api`, `backend/cmd/worker`, `backend/internal/{geo,regulations,occupancy,vehiclefit,routing,prediction,recommendation,community,sessions,ingestion,platform}`, `data/{pipelines,simulator,evaluation}`, `db`, `contracts`, `infra`, `tests`, `docs/adr`.
- Domain ports/adapters, no cyclic module writes; Go HTTP/WS and worker as separate processes, not a microservice fleet.
- Search: geospatial candidates → cheap rule filter → bounded route matrix → candidate-specific arrival/full-stay rules → fit/occupancy/prediction → explainable recommendations + discovery.
- Source-scoped dedupe, sequence/observed_at distinctions, append-only evidence, source arbitration and freshness. Commit state/version and outbox atomically; Redis ACK only after DB commit; duplicate event safe; WebSocket disconnect triggers authoritative snapshot re-fetch.
- `POST /v1/parking/search`, `GET /v1/parking/map`, `GET /v1/parking/resources/{id}`, `GET /v1/parking/coverage`, parking-sessions, community report endpoints; WS details to finalize at M6. Search execution COMPLETE/PARTIAL/FAILED is not data coverage.
- Never assert data licensing, legality, sensor freshness, parking availability, SLO/benchmark achievement unless specifically verified.

## D. M0 evidence ledger (truthfully separate fact from measurement)

### Confirmed public sources

1. LADOT metered inventory, dataset `s49e-q6j2`: https://data.lacity.org/d/s49e-q6j2
2. LADOT last-known occupancy, `e7h6-4a3e`: https://data.lacity.org/d/e7h6-4a3e
3. LADOT SMART Grant *Code the Curb* DTLA supporting dataset, Set 1: https://rosap.ntl.bts.gov/view/dot/94217 ; publication 2026-04-10, CC BY 4.0 metadata/attribution noted on page.
4. Policy JSON: https://rosap.ntl.bts.gov/view/dot/94217/dot_94217_DS11.json — the web reader opened source JSON. Top-level `version`, `time_zone`, `last_updated`, `author`, `data` with nested policy objects. At least one `rules[].user_classes` entry is a scalar string (`"car"`) while others are arrays; normalize deliberately. Observed activities include `travel`, `no travel`, `undesignated`, `no stopping`; `rate:0` alone does **not** establish legal free parking.
5. Zone JSON: https://rosap.ntl.bts.gov/view/dot/94217/dot_94217_DS13.json — confirmed listed as downloadable supporting dataset, **full payload NOT parsed** due >4 MB web reader cap; this runtime cannot DNS-resolve the host for direct download.
6. See `M0_06_CODE_THE_CURB_DISCOVERY_2026-11-18.md` for the official report's published project-scale totals, which are **third-party published counts, not measured independent imports**.

### Audit checkpoints still OPEN

- [ ] Download full Zones and Policies JSON in a network-enabled environment; capture URLs, timestamps, SHA-256, original license/attribution.
- [ ] Inspect actual Zone schema/geometry and identify **all** policy references; check duplicate/missing IDs and inconsistent geometries.
- [ ] Compute **Zone → Policy join rate** with numerator/denominator and unresolved reference examples.
- [ ] Tabulate observed activities, time spans, user class variability, overlap/conflicts, source freshness; **do not classify every `rate=0` or `undesignated` as free legal curb**.
- [ ] Check ordinary-car eligibility for complete example stays including weekday/daytime, overnight, weekends, street sweeping and permits; if restriction coverage is incomplete mark UNKNOWN.
- [ ] Join metered inventory ↔ last-known occupancy by source-scoped `SpaceID`, independently measure source age and **after-hours** freshness; original source pages listing record counts are not a join statistic.
- [ ] Select and actually audit 20 DTLA block faces with side-specific evidence, supplementing government data with current signs where obtainable (0/20 verified as of this note).
- [ ] Compare Westwood only after DTLA data audit; Downtown has stronger available curb dataset but is not necessarily better for free-residential product viability.
- [ ] Record explicit GREEN/AMBER/RED recommendation for actual selected pilot scope.

### M0-07 decision and precise result of THIS round

**Result: SOURCE CONTRACT CLARIFIED; EMPIRICAL COVERAGE STILL BLOCKED.** Public USDOT repository independently reconfirmed the Zones supporting file and public licensing notice; browser access to Zones exceeded reader limit (`>4,194,305` bytes), while direct Python download failed at DNS resolution. Policies JSON accessible through web and confirms nested rules and mixed user-class type. No valid zone-policy join percentage can be claimed. This is an infrastructure/file-access blocker, **not a failure of the source or proof of unavailable data**.

**Next highest value action:** In a normal network-enabled local environment, download the full official Zone JSON and Policy JSON; then run a small independent M0 research audit, inspect the first actual block faces, report denominators/missing mappings. Do **not** begin inferred-legal map or wide rollout before this verification. If full file can be attached in chat, we can analyze locally without relying on public runtime network.

## E. Milestone plan

M0 real-data feasibility and pilot decision → M1 monorepo/Go+React+PostGIS foundation → M2 real GIS map → M3 rules/eligibility → M4 routing/search → M5 occupancy/simulation/inbox/outbox/Redis → M6 WebSocket/reconnect → M7 private sessions/consent/community → M8 deploy/measure/harden/demo.

Build vertical slices. PR-level acceptance requires executable proof, correctness tests, contract alignment, reproducibility and engineering review. Codex works in bounded tasks; the user decides architecture and reviews changes. Never claim success from synthetic performance metrics or unrun tests.

## F. User collaboration and file delivery preferences

- User wants substantive architecture and project understanding; Codex can implement later but user owns technical choices.
- **Until user explicitly begins implementation, do not write production implementation code or Codex implementation prompts.** M0 audit/research tooling is distinct and only when requested.
- For each new research/engineering round, **give exactly one newly created/updated downloadable artifact**, never re-offer all older ZIPs. The user has archived previous files and can provide them later.
- This file is the cross-chat handoff: if a new session lacks original chat history, **read this and the earlier source documents before coding**, and call out discrepancies instead of guessing.

## G. Source document names user has saved

- `ARCHITECTURE_BASELINE_v1.0.md`
- `M0_DATA_FEASIBILITY_PLAN.md`
- `M0_EXECUTION_REPORT_2026-11-17.md`
- `M0_04_RESIDENTIAL_CURB_FEASIBILITY_2026-11-18.md`
- `M0_05_PILOT_SHORTLIST_2026-11-18.md`
- `M0_06_CODE_THE_CURB_DISCOVERY_2026-11-18.md`
- `M0_04_BLOCK_FACE_AUDIT_TEMPLATE.csv`
- `m0_meter_audit.py`

These named documents may cover detail this handoff compresses; obtain originals before implementing their detailed specifications.
