# CurbOS Project State

Updated 2026-11-19.

- **Milestone** M1, Runnable Foundation.
- **PR-01** Merged in [PR #1](https://github.com/KaiwenMo1/CurbOS/pull/1) as `d023604`. [PR CI passed](https://github.com/KaiwenMo1/CurbOS/actions/runs/44622343482).
- **PR-02** Merged in [PR #2](https://github.com/KaiwenMo1/CurbOS/pull/2) as `bcfe3ec`. The [PR CI run passed](https://github.com/KaiwenMo1/CurbOS/actions/runs/44624913175).
- **PR-03** Merged in [PR #3](https://github.com/KaiwenMo1/CurbOS/pull/3) as `91bfbad`. The API provides process liveness and bounded PostgreSQL readiness with the PostGIS and Goose baseline. [PR CI passed](https://github.com/KaiwenMo1/CurbOS/actions/runs/44628781477).
- **PR-04** Local engineering review complete on `m1/pr-04-map-shell` from `91bfbad`. The responsive shell shows Going Home and Going Out modes and keeps the parking-data notice above the map. MapLibre is opt-in through an approved style URL.
- **PR-04 evidence** `make check` (18 frontend tests), `make db-test`, `make api-test`, and `actionlint` passed. Chromium production previews verified desktop, tablet, and mobile layouts, keyboard controls, dark and reduced-motion settings, and zero external requests by default. A local style and controlled failures verified map re-mount and worker cleanup, startup timeout and cancellation, failed style and worker requests, and WebGL fallback.
- **Open validation** Live basemap providers, Firefox, and Safari have not been tested. M0 data verification stays open under the [M0/M1 acceptance gates](../docs/milestones/M0_M1_ACCEPTANCE_AND_GATES.md).
- **Next review gate** Human review of the PR-04 draft and its [hosted checks](https://github.com/KaiwenMo1/CurbOS/actions?query=branch%3Am1%2Fpr-04-map-shell) before any merge.

[AGENTS.md](../AGENTS.md) and the [accepted ADRs](../docs/architecture/DECISION_REGISTER.md) govern architecture. Update this record when PR status, evidence, blockers, or the next authorized action changes. Include an ADR compliance check and Engineering Learning Note in each PR. Propose changes to accepted ADRs for human review before implementing them.
