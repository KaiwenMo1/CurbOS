# CurbOS Project State

Updated 2026-11-19.

- **Milestone** M1, Runnable Foundation.
- **PR-01** Merged in [PR #1](https://github.com/KaiwenMo1/CurbOS/pull/1) as `d023604`. [PR CI passed](https://github.com/KaiwenMo1/CurbOS/actions/runs/44622343482).
- **PR-02** Local engineering review completed on `m1/pr-02-postgis` from `d023604`. The reviewed change is ready for a pull request targeting `main`.
- **Evidence** `make check`, `make db-test`, and `actionlint` passed. The database check ran in Ubuntu WSL with Docker Desktop 29.4.3 and Compose 5.1.3. It verified PostgreSQL 17.11, PostGIS 3.6.4 installed by Goose, recorded migration version 1, repeat execution, restart and recreation persistence, and failure handling for missing credentials, wrong credentials, and a stopped database. A separate run verified isolation from local Compose overrides.
- **Hosted evidence** See the [PR-02 branch checks](https://github.com/KaiwenMo1/CurbOS/actions?query=branch%3Am1%2Fpr-02-postgis) for the current result. M0 data verification stays open under the [M0/M1 acceptance gates](../docs/milestones/M0_M1_ACCEPTANCE_AND_GATES.md).
- **Next review gate** Human review of the published PR-02 diff and hosted checks before any merge or PR-03 work.

[AGENTS.md](../AGENTS.md) and the [accepted ADRs](../docs/architecture/DECISION_REGISTER.md) govern architecture. Update this record when PR status, evidence, blockers, or the next authorized action changes. Include an ADR compliance check and Engineering Learning Note in each PR. Propose changes to accepted ADRs for human review before implementing them.
