# CurbOS — First Codex Task Pack (Planning Only)

**Stage:** Ready to paste one task at a time into Codex **after** you authorize coding. Do NOT ask Codex to implement every PR in one session. References use paths relative to repo root.

## Default preamble for every Codex PR
> Read `AGENTS.md`, `docs/architecture/DECISION_REGISTER.md`, and `docs/milestones/M1_IMPLEMENTATION_SPEC.md`. Follow accepted ADR-001–028. Inspect existing files/git status before editing; identify any conflicts. Limit work to the named PR. Use the smallest coherent implementation, no speculative layers or fake parking data. Add relevant tests and exact run instructions. Run verification when possible, state what was not run. At completion report changed files, rationale, test evidence, open risks and an Engineering Learning Note. Do not start the next PR until I review this one.

## PR-01 — Repository Foundation (START HERE)
**Prompt:**
> Using the default preamble, create the smallest usable CurbOS monorepo foundation. Keep the planning documents and M0 research intact. Add a minimal Go module with an executable API entrypoint placeholder that compiles, and a minimal Vite React TypeScript app that builds with a plainly labeled no-data landing page (no real map tiles required). Create root README with prerequisites and explicit start/test commands, a safe `.gitignore`, example environment config (no secrets), consistent formatting/lint/check scripts, and basic GitHub Actions workflow for current builds. Choose and pin practical versions for Go/Node/package manager and record them. Do not implement database, occupancy, legal claims, Redis, WebSocket, OSRM, auth, or actual parking APIs in this PR. Include smoke/unit tests that are reasonable for the foundation. Stop for review.
**Exit criteria:** reproducible Go build and TS build; CI syntax/static validation; README from clean checkout; no fake data, no accidental credentials.

## PR-02 — Local PostGIS & Migrations
**Prompt:**
> Using the default preamble, add local PostgreSQL/PostGIS via Docker Compose, health checks, persisted development volume, safe env handling, and a minimal goose migration that establishes PostGIS support and only required base schemas. Verify first boot, repeat boot, migration apply and failed DB startup behavior. No domain tables or sample parking legality. Add integration test/instructions. Stop for review.
**Exit criteria:** DB starts/restarts, migration verified, correct failure behavior.

## PR-03 — Go Operational API
**Prompt:**
> Using the default preamble, implement documented `GET /healthz` and `GET /readyz` with bounded DB check and correct HTTP status codes. Keep transport, application logic and DB adapter minimally separated; choose interfaces only at actual test/external boundaries. Add tests for healthy/degraded conditions and configuration validation. No parking search endpoints yet. Stop for review.
**Exit criteria:** liveness independent of DB; readiness reflects DB failure; integration test passes.

## PR-04 — Map-First Frontend Shell
**Prompt:**
> Using the default preamble, turn the frontend into a responsive MapLibre-capable map-first shell, with clearly labeled no verified parking data. If a legally permitted style/tiles source is not configured, render a documented blank-map fallback; never hardcode unverifiable token, invented pins or misleading legal cues. Add UI tests for empty/error states. Stop for review.
**Exit criteria:** desktop/mobile layout, safe fallback, TS build and tests.

## PR-05 — Integration & Quality Gate
**Prompt:**
> Using the default preamble, add real browser-to-API connectivity check, reliable local startup/teardown runbook, build/test/migration CI integration and one meaningful end-to-end smoke path. Do not add product endpoints, accounts, WebSocket or source imports. Capture exact verified commands and CI outcomes. Stop for review.
**Exit criteria:** fresh checkout end-to-end; no mocks-only connectivity claim; clean CI evidence.

## Parallel **M0 data audit** (separate from app PRs)
- Verify/checksum official source files on a user-accessible machine; run existing `tools/m0/m0_08_cds_audit.py` and `tools/m0/m0_meter_audit.py` on actual datasets, not fixtures.
- Return raw counts with denominators, unresolved IDs, geometry error samples, `eventtime` freshness distribution at a clearly stated as-of time, license and source timestamps.
- Require explicit human review of data evidence; no auto-promoted legal recommendations.

## Review gate between PRs
The user should read the diff and ask: 'What concrete capability was added? What failure did we test? Is this within approved ADR scope? What does it teach me about Go/PostGIS/React?' If any PR cannot demonstrate a working slice, refine it instead of starting another.
