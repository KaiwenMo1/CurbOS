# CurbOS — AGENTS.md (Coding Agent Rules)

**Status:** Approved execution guardrails for M0–M1 planning. Read this first, then `docs/core/ARCHITECTURE_BASELINE_v1.0.md`, `docs/architecture/DECISION_REGISTER.md`, and the applicable milestone spec. **Do not implement code unless the human explicitly asks you to begin a task.**

## Mission
Build a trustworthy street-parking-first map application, **not** a parking guarantee or a simulator masquerading as real data. Two entry modes, Going Home and Going Out, share the same search engine. The stack and constraints follow ADR-001–028.

## Hard product invariants
1. `UNKNOWN` does **not** mean vacant, legal, free, fitting, or 50% probable. Never silently cast `NULL` to a positive answer.
2. Discovery is not Verified Recommendations. Legality is evaluated for the **entire requested stay**, vehicle, permits, candidate-specific arrival and local timezone, with evidence completeness. Posted signs and temporary restrictions may supersede a dataset.
3. A block-face/centerline is not measured curb geometry; do not derive observed free slots as curb length / car length. Distinguish delineated spaces, flexible curb zones, and facilities; avoid double counting parent/child resources.
4. Last-known sensor status is not guaranteed current or guaranteed free at arrival. Freshness and source clocks matter; community area-level feedback is not direct sensor truth.
5. Simulated events/data are isolated by DB, Redis and credentials. Fixtures **must be labeled synthetic**. Never publish synthetic performance or accuracy as real-world measurements.
6. Save My Parking data is private by default. No passive publication of personal coordinates; explicit opt-in is required to contribute community evidence.
7. Source ingestion follows **ADR-028**: immutable raw snapshot → validated staging → atomic published data version; previous published version remains readable if validation/publish fails.
8. Production-facing claims, counts, links and benchmarks require real evidence, not fabricated statistics.

## Architecture and dependencies
- Monorepo: `apps/web` (React/TS/Vite/MapLibre/TanStack Query), `backend` (Go modular monolith, HTTP entrypoint, later worker), `data` (Python ETL/simulator/evaluation), `db`, `contracts`, `infra`, `tests`, `docs`.
- PostgreSQL/PostGIS is the authority; `pgx`, `sqlc`, `goose`. Redis Streams + PostgreSQL Inbox/Outbox are **later** M5, not M1. WebSocket with snapshot reconciliation is **later** M6, not SSE. Routing adapter/OSRM starts M4.
- Domain ownership: `geo`, `regulations`, `occupancy`, `vehiclefit`, `routing`, `prediction`, `recommendation`, `community`, `sessions`, `ingestion`, `platform`. No circular dependencies or direct cross-domain writes; application use cases orchestrate ports/adapters. Add interfaces only at real boundaries.
- Commit schema changes through numbered goose migrations; never mutate prod DB manually. Keep migration order and generation reproducible.

## Agent execution protocol (mandatory)
1. Scope check: identify current PR/task, read relevant ADR + contracts, state intended files and why. Do not implement future milestones or create dozens of empty packages.
2. Check environment and existing repo state. Do not overwrite human changes; record baseline git status. No unrequested broad refactors, infra substitutions, third-party APIs, privileged credentials or external uploads.
3. Implement one vertical slice with its tests. Keep semantic errors explicit, API models typed, source provenance and geometry precision preserved. Auth, location data and secrets need protection.
4. Run feasible tests/lints/build/migrations with exact commands; report **PASS / FAIL / NOT RUN** truthfully with environment limitations. Do not claim success from a command that was not run.
5. Submit a review summary: changed files, decision rationale/tradeoffs, tests, observed results, risks, rollback, and a short **Engineering Learning Note** (explain how it works and what could fail).
6. Pause at the PR boundary for human review before proceeding. When blocked, explain options; never silently relax legal/evidence correctness gates.

## M1 scope freeze
**Allowed:** minimal documented monorepo, local PostGIS, Go `/healthz` and `/readyz` (readiness checks DB), Vite/React app with a plainly labeled **empty/unsupported data** map shell, baseline goose migration with PostGIS enablement, reproducible smoke/integration tests, GitHub Actions CI. Local MapLibre rendering requires a documented permitted tile/style endpoint (do not invent a token); if none is configured, show an explicit empty/no-basemap state.

**Not allowed in M1:** claim real LA legal availability; import unverified curb rules; ranking, occupancy predictions, Redis, WebSocket, user sessions/auth, auto GPS tracking, notifications, any payment/reservation, K8s/microservices, fictional p95 values, phantom datasets. Keep database tables minimal until M2 domain requirements are pinned.

## Data provenance and privacy
- M0 scripts in `tools/m0` are research tools, not canonical production ETL. Track source URL, license, access date, SHA-256, source as-of timestamp and mapping assumptions.
- Do not log individual search origins, home addresses, private parked locations or user-submitted coordinates by default; redact logs and test data.
- Avoid collecting user accounts or precise location in M1. Do not add external telemetry by default.

## Test obligations
- M1: deterministic build; API live health/readiness and DB-down behavior; migration apply from clean DB; frontend build/test; CORS/origin/config smoke test if exposed; CI green or clearly blocked.
- M2+: import atomicity and rollback; invalid/missing policy relationships; topology/precision; contradiction and full-stay rule cases; M5+: duplicate/out-of-order/crash recovery; M6+: websocket stale/duplicate/reconnect resync; M7+: access control/consent/deletion.

## Handoff
Canonical architecture: `docs/core/ARCHITECTURE_BASELINE_v1.0.md` plus `docs/architecture/DECISION_REGISTER.md`. Latest task guidance: `docs/milestones/M1_IMPLEMENTATION_SPEC.md` and `docs/codex/M1_FIRST_PR_TASKS.md`. When files disagree, **accepted ADRs and explicit later human decisions** prevail; flag any unresolved conflict instead of guessing.
