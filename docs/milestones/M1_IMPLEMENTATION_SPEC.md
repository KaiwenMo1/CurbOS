# M1 — Implementation Specification: Runnable Foundation

**Status:** Ready for human review; not executed. **Goal:** a reproducible minimal end-to-end CurbOS skeleton using Go + React + PostGIS. **Design authority:** ADR-001–028, `AGENTS.md`.

## Why M1 exists
Prove the repository structure, local development setup, API ↔ DB connectivity, browser ↔ API communication and CI can work together **before** implementing data-heavy legal parking logic. M0 empirical audit proceeds in parallel.

## Allowed deliverables (incremental PRs)
- `backend/cmd/api` with configuration loader and operational `GET /healthz` and `GET /readyz` (no parking claims).
- `apps/web`: React + TS + Vite responsive shell and MapLibre container with explicit **No verified parking data available** state; no geolocated resources invented.
- `compose.yaml` for local PostgreSQL/PostGIS and app dev dependencies; env example (no secrets committed); persisted local DB volume; health checks.
- Minimal `db/migrations` goose baseline: create controlled extension/schemas **only as needed**, no 25 speculative empty tables; repeatable upgrade verification.
- `contracts/openapi` initially documents actual operational endpoints only; parking/search contract detailed in M4.
- GitHub Actions running Go unit/integration as feasible, TS typecheck/build/tests, migration check; instructions for required containers.
- README Quickstart and troubleshooting; one runnable end-to-end smoke test that proves Web→Go (and DB readiness in backend tests).

## Non-goals / explicitly deferred
Production-grade user accounts, precise GPS, community reports, occupancy state, sensor ingestion, full legal evaluator, search/recommendations, Redis, OSRM, WebSocket, simulator, ML predictions, production deployment, storage buckets. Do not add mock `VACANT` or `LEGAL` pins to public UI.

## Proposed PR sequence (work must stay small)
| PR | Scope | Acceptance |
|---|---|---|
| PR-01 | Minimal monorepo/toolchains/README/config and CI skeleton | Clean checkout; scripts/build targets documented; no scaffold bloat |
| PR-02 | Docker Compose PostGIS + goose baseline | Clean `up`; migration applied; DB readiness and failure handling tested |
| PR-03 | Go API health/readiness with DB adapter | `/healthz` works without DB; `/readyz` fails when DB inaccessible, succeeds when DB healthy; tests |
| PR-04 | React/TS/Vite + MapLibre empty state | UI builds, renders empty/no-data state, does not rely on unapproved tiles/token; responsive smoke test |
| PR-05 | Browser↔API integration, CI quality gate + documentation | Test proves actual configured API reachability; clean startup and teardown steps |

## Contract rules M1
- `GET /healthz`: process alive only; `200` body documented and stable; **must not lie about DB health**.
- `GET /readyz`: dependency readiness, including a bounded database ping; `503` (or explicit unavailable) while DB down. No user coordinates in responses.
- Config from env with validation and safe defaults. Distinguish dev, test and production; no shared production/simulation credentials. Do not put real production credentials in example env.
- Frontend must not infer API readiness from `healthz`; if representing backend availability use readiness or a documented API ping. Avoid cross-origin wildcard when credentials are enabled; explicit environment origin list.
- No actual parking-location/rules tables until M2 requirements confirm dimensions and source mappings.

## End-to-end acceptance scenarios
1. Fresh repo + documented prerequisites: `docker compose up` brings up configured dependencies and services without secret prompts beyond documented `.env` sample.
2. API process responds to `/healthz` even if DB temporarily unavailable, while `/readyz` correctly returns non-ready.
3. PostGIS extension availability can be verified on clean migration; multiple startups do not corrupt schema.
4. Web app loads and labels absence of verified data; API connectivity is exercised, not mocked exclusively.
5. CI executes automated tests on a clean checkout; no green claim without captured logs.
6. Shutdown/restart preserves expected local DB state; teardown commands are documented for clean test reset.
7. Secret scanning or reasonable checks detect committed credential patterns; logs don't include coordinates.

## Human review questions
- Why should `healthz` differ from `readyz`? What happens on a DB outage?
- Which part of the stack is authoritative and what constitutes a simulation?
- What does the UI say when there are no verified parking resources?
- What must be added before the app can claim a legal parking recommendation?

## Dependencies / risks
- Developer machine must have Docker, Go, Node/pnpm or npm, and relevant versions selected/locked at PR-01. Actual installations/versions not yet verified.
- Tiles/style licensing for MapLibre must be confirmed; **no hardcoded public tile use** without reviewing terms; fallback blank style/no-basemap state.
- Corporate or campus network may block some external map providers; local app must remain operable without live tiles.

## What counts as M1 Done
All five scoped PRs merged/reviewed, one-command local documented run, fresh-install CI pass evidence, API/database/UI integration proof, no unverifiable parking claims, updated project handoff and known gaps. No fake performance benchmarks.
