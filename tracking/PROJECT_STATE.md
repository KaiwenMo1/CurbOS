# CurbOS Project State

Updated 2026-11-21.

- **Milestone** M2 PR-07, Real-Source Readiness and Publication Gate. M1 foundation merged.
- **PR-01** Merged in [PR #1](https://github.com/KaiwenMo1/CurbOS/pull/1) as `d023604`. [PR CI passed](https://github.com/KaiwenMo1/CurbOS/actions/runs/44622343482).
- **PR-02** Merged in [PR #2](https://github.com/KaiwenMo1/CurbOS/pull/2) as `bcfe3ec`. The [PR CI run passed](https://github.com/KaiwenMo1/CurbOS/actions/runs/44624913175).
- **PR-03** Merged in [PR #3](https://github.com/KaiwenMo1/CurbOS/pull/3) as `91bfbad`. The API provides process liveness and bounded PostgreSQL readiness with the PostGIS and Goose baseline. [PR CI passed](https://github.com/KaiwenMo1/CurbOS/actions/runs/44628781477).
- **PR-04** Merged in [PR #4](https://github.com/KaiwenMo1/CurbOS/pull/4) as `9e9aa0b`. The responsive shell and opt-in MapLibre keep the parking-data notice above the map. [PR CI passed](https://github.com/KaiwenMo1/CurbOS/actions/runs/44633196245).
- **PR-05** Merged in [PR #5](https://github.com/KaiwenMo1/CurbOS/pull/5) as `d6ae0d7`. The browser checks PostgreSQL readiness through the existing Go API. The parking-data notice remains visible in every readiness state. [PR CI passed](https://github.com/KaiwenMo1/CurbOS/actions/runs/44663981910).
- **M2 PR-01** Merged in [PR #7](https://github.com/KaiwenMo1/CurbOS/pull/7) as `e0267c0`. The evidence schema enforces release and QA lineage in PostgreSQL.
- **M2 PR-02** Merged in [PR #8](https://github.com/KaiwenMo1/CurbOS/pull/8) as `f35265b`. The final 30-test synthetic suite and [hosted checks](https://github.com/KaiwenMo1/CurbOS/actions/runs/44702356395) passed. [Capture runbook](../data/cds_capture/README.md)
- **M2 PR-03** Merged in [PR #9](https://github.com/KaiwenMo1/CurbOS/pull/9) as `f10ec69`. It validates Stage Schema v2 and prepares private candidate packages. [Hosted checks passed](https://github.com/KaiwenMo1/CurbOS/actions/runs/44705155071). [Validation runbook](../data/cds_validate/README.md)
- **M2 PR-04** Merged in [PR #10](https://github.com/KaiwenMo1/CurbOS/pull/10) as `47776d3`. Private registration, independent verification and approval, and audited pointer changes are available for enrolled synthetic fixtures. [Publication runbook](../data/cds_publish/README.md)
- **M2 PR-05** Merged in [PR #11](https://github.com/KaiwenMo1/CurbOS/pull/11) as `b54c54e`. The pinned Discovery API closes historical pins and cursors on scope withdrawal. [Discovery API contract](../contracts/openapi/DISCOVERY.md)
- **M2 PR-06** Merged in [PR #12](https://github.com/KaiwenMo1/CurbOS/pull/12) as `52e80ea`. The browser uses the pinned Discovery API and shows no verified parking data in ordinary mode. [Frontend runbook](../apps/web/DISCOVERY.md)
- **M2 PR-07** The offline assessor verifies private artifacts, stage, candidate, and projection in a read-only transaction. The synthetic CDS suite passed 72 tests, including no database changes after successful or failed assessments. Real-source evidence remains `NOT_ASSESSED` and the publication decision remains `NO_GO`. [Readiness runbook](../data/cds_readiness/README.md)
- **M2 PR-07 review fix** [Draft PR #13](https://github.com/KaiwenMo1/CurbOS/pull/13) now reports supplied approval states and references as unverified assertions in schema v2. The 74-test synthetic suite passed. Technical integrity remains independently checked, and evidence and publication readiness remain blocked. [Readiness runbook](../data/cds_readiness/README.md)
- **Next review gate** Independent Review Round 2 on Draft PR #13. Authoritative attestation verification, real-archive assessment, independent rights and field review, and production publication authorization require separate decisions.

## M1 acceptance evidence

| Requirement | Status | Evidence |
|---|---|---|
| PR-01 pinned toolchains, repository foundation, and reproducible checks | PASS | `make bootstrap` and `make check` passed from a clean export of the PR-05 source. The latter ran 29 frontend tests, Go race tests, and both builds. |
| PR-02 PostGIS startup, Goose migration and persistence | PASS | `make db-test` and the combined gate applied and repeated the migration on PostgreSQL 17.11/PostGIS 3.6.4 and preserved history through restart and container recreation. |
| PR-03 liveness, readiness and outage behavior | PASS | `make api-test` passed. The browser gate also observed `/healthz` at 200 while `/readyz` returned 503. |
| PR-04 responsive map and honest evidence state | PASS | Merged PR-04 desktop, tablet, mobile, and fallback checks. PR-05 Chromium verified that trip mode and backend readiness changes preserve the configured map and no-data notice. |
| PR-05 browser-to-Go-to-PostGIS and startup/teardown runbook | PASS locally | `make e2e-test` verified real ready, database-down, recovered, and API-down responses in Chromium. The offline check and rejected proxy targets showed safe behavior. SIGINT and SIGTERM tests while PostgreSQL was paused confirmed process, build, container, and volume cleanup. |
| PR-05 hosted CI on GitHub | PASS | [Hosted foundation and end-to-end checks](https://github.com/KaiwenMo1/CurbOS/actions/runs/44663981910). |
| Truthful data boundaries and secret hygiene | PASS | The only test style is a temporary synthetic background. The browser gate checked the parking notice across states. The changed-file credential scan and planning manifest verification passed. |
| Engineering review, runbook, and handoff | PASS locally | The README covers startup, failure recovery, data-preserving teardown, and the one-command integration gate. Local self-review is complete. |
| PR-05 merge | PASS | [GitHub records PR #5 as merged](https://github.com/KaiwenMo1/CurbOS/pull/5). |

M0 data feasibility remains open. The current evidence provides no basis for verified parking recommendations. Live basemap providers and browsers other than Chromium were outside the PR-05 validation. [M0/M1 acceptance gates](../docs/milestones/M0_M1_ACCEPTANCE_AND_GATES.md)

**Engineering Learning Note.** Go returns 503 when PostgreSQL cannot satisfy the baseline probe, even as its liveness route continues returning 200. The Vite proxy returns 502 when Go is stopped. The browser displays these separately from a failed fetch, and an explicit retry recovers after the database resumes without restarting the browser or Go.

## M2 Design Research Backlog

- Compare CurbLR, Open Mobility Foundation CDS, SharedStreets Curb Map, OSM Parking Lanes, and GeoLibre against the existing CurbOS schema and evidence requirements.
- Keep God's Eye View, Argos Atlas, and World Monitor as inspirations for future geospatial and event intelligence. This research is deferred beyond M1.

[AGENTS.md](../AGENTS.md) and the [accepted ADRs](../docs/architecture/DECISION_REGISTER.md) govern architecture. Update this record when PR status, evidence, blockers, or the next authorized action changes. Include an ADR compliance check and Engineering Learning Note in each PR. Propose changes to accepted ADRs for human review before implementing them.
