# M3 PR plan and acceptance gates

**Reconciled sequence.** M3-00D records human design decisions. Coding requires separate explicit authorization after design review. Each implementation PR has a distinct first acceptance gate and retains regressions from prior slices. All six slices use isolated synthetic fixtures. [Decision register](M3_DESIGN_SPEC.md#design-decision-register) · [Acceptance matrix and owners](M3_TEST_MATRIX.md)

## PR-01 — Synthetic-only pure Go Minimal Core

- **Objective and code area.** Add an isolated pure Go function and table-driven synthetic fixtures in `backend/internal/regulations`. Evaluate already-normalized absolute UTC windows at exact events, using one exact fixture target, simple permits and explicit synthetic coverage/restriction assumptions. Return overall and first-class interval outcomes with deterministic reasons and evidence references.
- **Prerequisite.** M3-00D fixes the design scope and work limits. Wait for separate explicit coding authorization after design review.
- **Non-goals.** Public API, database access, runtime wiring, production data or authorization, certificate verification, precedence graphs, complex exemptions, textual time parsing or any civil/recurring normalization.
- **Tests and evidence gate.** T01–T07, T12–T14, T18, T20, T30, T34–T36, T44–T48 and T53. Check a one-second ban, coincident boundaries, P/X/U partition, coverage gaps, unknown permits, absent restriction-specific assumptions, shuffled order and corruption. T36 checks the inclusive 168 elapsed hours input limit. T47 exercises 256 rules, 1,024 raw temporal windows, 1,024 unique temporal boundaries and 2,048 evidence references. Count duplicate windows before filtering or deduplication, and preflight raw counts before input-sized allocations. Count start and end events separately, with a derived maximum of 2,050 endpoint entries including both request endpoints. Over-budget input fails without partial intervals or legal proof, even if a restriction starts at the first boundary. Verify the fixture trust boundary, then run Go race tests and `make check`.
- **Risk and rollback.** False permission from vacuous coverage or missing permit facts, losing short bans to sampling, or mistaking fixture inputs for authorization. Revert the isolated package and tests.
- **Done when** deterministic synthetic evaluation and partition invariants pass and the runtime and M2 gates are unaffected. Stop for review.

## PR-02 — Civil schedules, exceptions and maximum stay

- **Objective and code area.** Extend `backend/internal/regulations` and its package-local fixtures with the M3-02D normalizer. It projects explicitly pinned civil inputs and supported continuous elapsed caps to bounded absolute windows for the merged PR-01 evaluator.
- **Prerequisite.** PR-01 is merged. D1-A–E fix the synthetic semantics and D1-F requires bounded normalization. The candidate ceilings need explicit approval or revision. Coding requires separate explicit authorization. [Civil-time contract](M3_RULE_EVALUATION_CONTRACT.md#pr-02-civil-time-design)
- **Non-goals.** Live feeds, real jurisdiction datasets, textual request parsing, permit evidence verification, inferred prior dwell or a re-parking engine.
- **Tests and evidence gate.** T21–T29, T31–T33, T37 and T55–T57. Assert exact UTC partitions, explicit timezone error states, holiday uncertainty, the cap's expiration and one-nanosecond overrun, expansion at the limit and failure at limit plus one, and host-independent output. Count generated records against the existing core budgets and rerun the full PR-01 matrix. The future RFC 3339 transport/parser contract requires separate authorization.
- **Risk and rollback.** Wrong weekday after midnight, a bridged fold, an assumed occupancy start, and expansion that hides budget exhaustion can change a legal proof. Revert the civil normalization slice to retain the absolute evaluator.
- **Done when** the approved limits, exact projections and fail-closed semantics pass the synthetic acceptance matrix and `make check`. Existing M2 real-source and publication gates apply.

## PR-03 — Reviewed applicability, evidence and authority profiles

- **Objective and code area.** Extend `backend/internal/regulations` with reviewed scope, authority and precedence, complex exemptions, coverage certificate verification over synthetic evidence and exclusion-aware legal proof. Preserve potentially relevant excluded/unsupported records and check temporary order effective/observed dates and freshness.
- **Prerequisite.** Merged PR-02 and approved certificate and authority model under D2 and D3. Decide which gaps can change a decisive proof.
- **Non-goals.** Real DS11 normalization, inference of laws from tags, generic ordinal source precedence, attestation infrastructure and public permissions.
- **Tests and evidence gate.** T08–T11, T15–T16, T19, T49–T50, T52 and T54. Show that structural/geometry QA cannot replace coverage, unsupported or excluded records stay visible, temporary restriction silence does not prove permission, and community evidence needs independent authority. Retain the Minimal Core’s interval and unknown regressions.
- **Risk and rollback.** Misclassifying an unknown override as irrelevant or using a digest as authority. Revert the additional profile support. Earlier normalized synthetic scenarios keep their explicit assumptions.
- **Done when** test evidence shows no affirmative output from unverified completeness, rule order or merely structural Policy checks. `make check` passes.

## PR-04 — Additive rules evidence storage

- **Objective and code area.** Propose reviewed additive Goose files under `db/migrations`, constraints in `tests/db`, and disposable seed fixtures for the `rules` domain. Enforce versioned rule sets, exact target geometry lineage, evidence and review linkage, and same-scope/release keys. Keep the current Goose `00001`–`00006` byte-identical.
- **Prerequisite.** Merged PR-03 and separate review of D4, concrete keys, retention, trusted writes and read-only access. Choose next migration number against updated main.
- **Non-goals.** Real ingest, ACL changes to M2, installation of production reviewers/operators, public grant changes, and any active pointer update.
- **Tests and evidence gate.** T51. Run `bash db/goose.sh validate`, `make db-test`, and isolated Up/repeat/Down tests. Attempt mismatched batches, releases, targets, artifacts, geometry and approval IDs. Check rejection and protected history, plus existing M2 synthetic tests.
- **Risk and rollback.** Cross-release joins, destructive Down and overly broad owner access. Keep grants limited to the future rules boundary. Preserve retained evidence. Down is a disposable-only check while operational recovery uses a forward correction or disables the internal path.
- **Done when** clean and repeat migrations, constraint failures and rollback preserve M2 schema and evidence invariants. No real rows exist.

## PR-05 — Internal coherent evaluation and current-use gate

- **Objective and code area.** Add one internal application use case after review of package names, proposed under `backend/internal/regulations/evaluation`, with a pgx adapter under `backend/internal/platform/postgres`. Load the exact eligible synthetic snapshot, evaluate it and recheck authorization before returning a live internal result. Keep testing entry points private under `backend/internal` and `tests/db`.
- **Prerequisite.** Merged PR-04. Agree on D4 snapshot isolation, eligible historical pin rules, revocation generation, role boundaries, sanitized failure behavior and deterministic interleaving harness.
- **Non-goals.** New public or admin routes, synthetic runtime switches, public eligibility, M2 API rework and activation privileges.
- **Tests and evidence gate.** T17, T38–T39 and T41–T43 in disposable PostgreSQL with explicit synchronization around load and recheck. Assert permissions, cancellation, cross-release rejection, retained snapshot identity and whole-stay `UNKNOWN` with no restricted references after revocation. Run `make api-test`, `make cds-test` and `make check`.
- **Risk and rollback.** A pointer switch may cause mixed reads or a revoked conclusion. Verify both the immutable snapshot and fresh serving eligibility and document the recheck's observation boundary. Remove the unexposed use-case hookup and leave retained evidence intact.
- **Done when** an internal result is coherent under concurrent releases and unavailable after revocation, and existing Discovery contract tests pass.

## PR-06 — Synthetic replay and release acceptance evidence

- **Objective and code area.** Add a bounded, separately authorized synthetic audit replay path and tests in the private evaluation package, plus a milestone runbook in `docs/milestones`. Demonstrate replay from frozen inputs/clock and version-identifiable decisions through the internal boundary.
- **Prerequisite.** Merged PR-05 and an approved synthetic-only audit policy under D4 for access, minimum request facts and denied/revoked cases.
- **Non-goals.** Persisting real user evaluations, adopting a real approval service, operating on a private archive without permission, and public legal claims or recommendations.
- **Tests and evidence gate.** Own T40 and gather regression evidence for the full matrix, including withdrawal/rollback and M2 ordinary no-release behavior. Run `make check`, `make db-test`, `make api-test`, `make cds-test`, and the existing Chromium gate with disposable inputs where feasible. Record PASS / FAIL / NOT RUN.
- **Risk and rollback.** Historical conclusions could be reused as current authority or leak restricted references. Test audit purpose tags, denials and safe redaction. Disable the replay path and retain prior receipts under approved retention.
- **Done when** proof reproduction and live/replay isolation are independently reviewed, exact tests and limitations are recorded, and M2 NO-GO still holds.

## Acceptance decisions beyond synthetic engineering

| Gate | Evidence for human approval |
|---|---|
| Synthetic implementation start | Give separate explicit coding authorization after PR-00 design review. The approved Minimal Core design leaves M2 engineering accepted for the bounded synthetic slice, real-source acceptance blocked and public publication NO-GO. |
| Synthetic engineering completion | Every scoped proof, interval, consistency and denial scenario has deterministic evidence or an explicitly accepted exception. Existing Discovery and baseline gates remain green. Document audit, rollback, gaps and non-goals before review. |
| Private real-source evaluation | Separately approve D5, exact sources and usage rights, independently verified field/side, jurisdiction and rule evidence, coverage and freshness thresholds, real archive replay, and who may access the results. Close or explicitly disposition the applicable M2 blocker register items. Synthetic tests are engineering evidence only. |
| Real public legal claims | Separately approve D6 after M2 real-source acceptance and real serving authorization, authoritative M3 evidence for full-stay outcomes, and reviewed access and operational controls. Demonstrate withdrawal, bounded staleness and replay isolation. Real public serving remains NO-GO until explicitly approved. |

No proposed PR adds search, routing, ranking, occupancy, prediction, payment, a legal API or frontend recommendations. [M2 blocker register](M2_ACCEPTANCE_REPORT.md#blocker-register) · [Accepted ADRs](../architecture/DECISION_REGISTER.md)
