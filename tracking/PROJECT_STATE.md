# CurbOS Project State

Updated 2026-11-19.

- **Milestone** M1, Runnable Foundation.
- **PR-01** Merged in [PR #1](https://github.com/KaiwenMo1/CurbOS/pull/1) as `d023604`. [PR CI passed](https://github.com/KaiwenMo1/CurbOS/actions/runs/44622343482).
- **PR-02** Merged in [PR #2](https://github.com/KaiwenMo1/CurbOS/pull/2) as `bcfe3ec`. The [PR CI run passed](https://github.com/KaiwenMo1/CurbOS/actions/runs/44624913175).
- **PR-03** Local engineering review completed on `m1/pr-03-api-health` from `bcfe3ec`. The API provides process liveness and bounded PostgreSQL readiness with the PostGIS and Goose baseline.
- **PR-03 evidence** `make check`, `make db-test`, `make api-test`, the uncached Go race tests, and `actionlint` passed locally. The isolated database tests verified readiness around migration and outage, graceful drain with an active probe, and forced shutdown with a checked-out pool connection. The built API started with PostgreSQL down and exited cleanly on SIGINT and SIGTERM.
- **Hosted evidence** See the [PR-03 branch checks](https://github.com/KaiwenMo1/CurbOS/actions?query=branch%3Am1%2Fpr-03-api-health) for the current result. M0 data verification stays open under the [M0/M1 acceptance gates](../docs/milestones/M0_M1_ACCEPTANCE_AND_GATES.md).
- **Next review gate** Human review of the draft PR-03 diff and hosted checks before any merge or PR-04 work.

[AGENTS.md](../AGENTS.md) and the [accepted ADRs](../docs/architecture/DECISION_REGISTER.md) govern architecture. Update this record when PR status, evidence, blockers, or the next authorized action changes. Include an ADR compliance check and Engineering Learning Note in each PR. Propose changes to accepted ADRs for human review before implementing them.
