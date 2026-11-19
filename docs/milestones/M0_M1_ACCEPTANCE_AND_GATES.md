# M0/M1 Acceptance & Boundary Checklist

## M0 — Evidence is an open gate
| Work item | Required output | Current status |
|---|---|---|
| Official source catalog | links, field definitions, license, retrieved/source-as-of times | PARTIAL |
| LADOT meter inventory | real count, duplicates, missing geometry, source freshness | NOT MEASURED |
| LADOT sensor join | SpaceID match rate with denominators, per-source freshness | NOT MEASURED |
| DTLA CDS Zones & Policies | full file integrity, join counts, type coverage, unresolved refs | NOT MEASURED |
| Residential 20 block-face audit | actual samples with sign/permit/sweeping/time-specific evidence | 0/20 verified |
| Final product pilot | evidenced DTLA/Westwood/etc tradeoff and go/no-go | NOT DECIDED |

Research scripts and synthetic fixtures in `tools/m0/` are **not** proof of real measured results. If external downloads fail, record blocker and continue M1 foundation in parallel.

## M1 — Start condition
Architecture accepted through ADR-028; app foundation can be started only after explicit user request. No claims of verified legal/free/vacant parking.

## M1 — Completion requirements
- [ ] PR-01 pinned toolchain, minimal repo Go/React scaffolding, README, basic CI; verified from clean checkout.
- [ ] PR-02 PostGIS Docker Compose + goose migration and restart test.
- [ ] PR-03 Go API health vs readiness, including DB outage test.
- [ ] PR-04 responsive MapLibre shell; honest no-data state with lawful tiles fallback.
- [ ] PR-05 full local browser→Go integration test, CI and runbook.
- [ ] No simulator/real-production data overlap; no fabricated parking resources, legal claims, or benchmark numbers.
- [ ] Code review, known risks, Engineering Learning Notes, handoff updates.

## M2+ gate before displaying real curb geometry
ADR-028 atomic publication, data lineage and an explicit uncertainty/coverage legend. M3 verified recommendations require independently checked full-stay rules evidence; M5 occupancy requires event-source freshness and idempotence tests; M7 sessions require privacy/consent boundaries.
