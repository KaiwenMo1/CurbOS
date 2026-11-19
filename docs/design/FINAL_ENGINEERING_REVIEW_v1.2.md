# CurbOS — Final Engineering Design Review v1.2

**Date:** 2026-11-18  |  **Scope:** coding readiness and remaining gates, **not** implementation.

## Decisions frozen for M1 planning
- ADR-001–028 confirmed; `docs/architecture/DECISION_REGISTER.md` is the single compact register.
- Modular Go API + separate eventual Go worker, PostGIS authoritative database, Python M0 audit and later ETL, React/MapLibre frontend. WebSocket (not SSE) is the confirmed live protocol, but not implemented in M1.
- Raw immutable snapshot → staging validation → atomic publication is ADR-028 and becomes a **M2** acceptance gate, not an excuse to build every ingest component in M1.
- Data source and geometry precision must remain explicit; rules may be incomplete. Search API must separately signal VERIFIED RECOMMENDATIONS and DISCOVERY, nullable occupancy/fit/price and evidence freshness. No legal search in M1.

## Hard blockers vs non-blockers
| Item | Ready? | Consequence |
|---|---|---|
| Monorepo, local dev infra and CI | **YES for planned M1 execution** | Can build no-claims foundation |
| Actual LADOT Zones and Policies full audit | **NO** | Block full CDS import quality claims and pilot validation |
| DTLA free-legal curb coverage | **NO** | Block public verified free parking claims |
| Real sensor join/freshness distributions | **NO** | Block measured occupancy/prediction claims |
| 20 block-face legality sample | **NO** | Block representative legal coverage claims |
| M2 staging/pub implementation | **NOT STARTED** | Planned after M1, needs independent tests |

## Cross-cutting engineering agreements
1. **Contracts:** contract-first interfaces with explicit unknown and version status. Generate typed clients later when actual endpoint scope requires it. `/healthz` and `/readyz` are M1 operational endpoints, not invented parking API behavior.
2. **Transactions:** enforce atomic DB changes within owned use cases; Redis is never authoritative, and replay/idempotency are tested before eventing rollout.
3. **Releases:** one incremental vertical slice per PR, executable, tested and reviewed. No speculative microservices, Kafka, autoscaling/K8s or unsupported ML probability.
4. **Observability:** structured application errors and health diagnostics in M1; OpenTelemetry and production dashboards added only with a real use case. Avoid location/PII logs.
5. **Security:** secrets only via ignored environment variables/secrets manager, least privilege and DB roles as feasible; origin restrictions; no default exposure of DB to public network.
6. **Frontend honesty:** M1 map shell explicitly says no verified parking data; an empty map never implies no curb parking exists.
7. **Source of truth:** this versioned pack + user-confirmed ADRs; earlier milestone docs are historical supporting details, not conflicting authority.

## Coding start criteria
M1 can begin once the user gives an explicit instruction to execute a Codex task and the agent checks repo state. This planning package alone does not mean code was written. M2 real-data legal claims remain evidence-gated.

## Proposed review checkpoint
Review PR-01 repo skeleton and toolchain after tests, before allowing PR-02. No arbitrary deadline, no unverified claims of build success.
