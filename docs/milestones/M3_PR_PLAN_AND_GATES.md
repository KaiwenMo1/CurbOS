# M3 PR plan and acceptance gates

**Proposed sequence.** PR-00 authorizes design review only. Each implementation PR requires explicit scope authorization, independent review of the actual diff and CI, and a human merge decision. All six proposed implementation PRs can be evaluated with isolated synthetic fixtures. [Decision register](M3_DESIGN_SPEC.md#design-decision-register) · [Acceptance matrix](M3_TEST_MATRIX.md)

## PR-01 — Pure Go full-stay evaluator

- **Objective and code area.** Add `backend/internal/regulations` with a small pure function and table-driven tests. Accept already normalized, bounded absolute time intervals, one exact synthetic target, coarse vehicle and opaque permit facts, and trusted synthetic fixture snapshots. Compose interval proofs into `PERMITTED`, `PROHIBITED` or `UNKNOWN`. Start with permission, prohibition and simple permit-only applicability.
- **Prerequisite.** Explicit approval of D1–D4 for the first slice, including the negative-proof requirement, input limits and stable status/reason vocabulary.
- **Non-goals.** Calendar expansion, production authority profiles, raw source adapters, new dependencies, SQL, application wiring, HTTP, and any real rules or data.
- **Tests and evidence gate.** T01–T07, T12–T14, T18, T20, T34–T36 (typed stay validation and bounded instants), and T44 with absolute inputs. Add interval partition invariants and Go race tests. Prove that a gap cannot produce permission, an unauthorized effect cannot become decisive, and each legal outcome leaves other dimensions unassessed.
- **Risk and rollback.** False permission from vacuous coverage, treating unknown permits as absent, or ignoring interval boundaries. Revert the unconnected package and its tests.
- **Done when** deterministic synthetic cases and `make check` pass. The Go binary continues to expose only existing routes. Stop for review.

## PR-02 — Civil schedules, exceptions and maximum stay

- **Objective and code area.** Extend `backend/internal/regulations` and its package-local test fixtures for versioned civil schedule expansion, pinned timezone input, holiday and seasonal exceptions, absolute temporary restrictions and supported maximum-stay semantics.
- **Prerequisite.** Merged PR-01 and explicit approval of D1's timezone, calendar, fold/gap and duration choices.
- **Non-goals.** Live holiday feeds, authored jurisdiction datasets, paid parking calculation, inferred previous dwell, and M2 edits.
- **Tests and evidence gate.** T21–T34 and T37, with one frozen synthetic timezone fixture and exact UTC assertions for both folds, spring gaps, half-open boundaries and the cap. Bound transitions, date iteration and interval counts. Pass T43 work-budget checks and preserve all PR-01 cases.
- **Risk and rollback.** Wrong weekday after midnight, normalization that bridges a fold, and wall-clock durations substituted for elapsed duration. Revert the added schedule behavior and retain the absolute contract.
- **Done when** tests are reproducible across host timezones using the same fixture data, including holiday uncertainty and unsupported accumulation, and `make check` passes.

## PR-03 — Reviewed applicability, evidence and authority profiles

- **Objective and code area.** Extend `backend/internal/regulations` with exact scope and side applicability checks, explicit authority/exception relationships, evidence freshness and completeness proofs, and synthetic fixture assembly. Treat unsupported source shapes as scoped gaps with their original lineage.
- **Prerequisite.** Merged PR-02 and approved synthetic authority and coverage model under D2 and D3. Review which inputs may be missing without changing a decisive proof.
- **Non-goals.** Real DS11 normalization, inference of laws from tags, generic ordinal source precedence, attestation infrastructure and public permissions.
- **Tests and evidence gate.** Complete T08–T16 and T18–T19, including wrong class, unresolved contradictions, wrong-side binding, approved narrow precedence, unsupported policy and stale evidence. Cover T42 invalid profiles and T44 canonical ordering. Test geometry/version mismatch and the distinction between binding a claim and verifying authority.
- **Risk and rollback.** Misclassifying an unknown override as irrelevant or using a digest as authority. Revert the additional profile support. Earlier normalized synthetic scenarios keep their explicit assumptions.
- **Done when** test evidence shows no affirmative output from unverified completeness, rule order or merely structural Policy checks. `make check` passes.

## PR-04 — Additive rules evidence storage

- **Objective and code area.** Propose reviewed additive Goose files under `db/migrations`, constraints in `tests/db`, and disposable seed fixtures for the `rules` domain. Enforce versioned rule sets, exact target geometry lineage, evidence and review linkage, and same-scope/release keys. Keep the current Goose `00001`–`00006` byte-identical.
- **Prerequisite.** Merged PR-03 and separate review of D4, concrete keys, retention, trusted writes and read-only access. Choose next migration number against updated main.
- **Non-goals.** Real ingest, ACL changes to M2, installation of production reviewers/operators, public grant changes, and any active pointer update.
- **Tests and evidence gate.** `bash db/goose.sh validate`, `make db-test`, and isolated Up/repeat/Down tests. Attempt mismatched batches, releases, targets, artifacts, geometry and approval IDs. Check rejection and protected history, plus existing M2 synthetic tests.
- **Risk and rollback.** Cross-release joins, destructive Down and overly broad owner access. Keep grants limited to the future rules boundary. Preserve retained evidence. Down is a disposable-only check while operational recovery uses a forward correction or disables the internal path.
- **Done when** clean and repeat migrations, constraint failures and rollback preserve M2 schema and evidence invariants. No real rows exist.

## PR-05 — Internal coherent evaluation and current-use gate

- **Objective and code area.** Add one internal application use case after review of package names, proposed under `backend/internal/regulations/evaluation`, with a pgx adapter under `backend/internal/platform/postgres`. Load the exact eligible synthetic snapshot, evaluate it and recheck authorization before returning a live internal result. Keep testing entry points private under `backend/internal` and `tests/db`.
- **Prerequisite.** Merged PR-04. Agree on D4 snapshot isolation, eligible historical pin rules, revocation generation, role boundaries, sanitized failure behavior and deterministic interleaving harness.
- **Non-goals.** New public or admin routes, synthetic runtime switches, public eligibility, M2 API rework and activation privileges.
- **Tests and evidence gate.** T17, T38, T39, T41–T43 in real disposable PostgreSQL with explicit synchronization around load and recheck. Assert permissions, cancellation, cross-release rejection and snapshot version identity. Run `make api-test`, `make cds-test` and `make check`.
- **Risk and rollback.** A pointer switch may cause mixed reads or a revoked conclusion. Verify both the immutable snapshot and fresh serving eligibility and document the recheck's observation boundary. Remove the unexposed use-case hookup and leave retained evidence intact.
- **Done when** an internal result is coherent under concurrent releases and unavailable after revocation, and existing Discovery contract tests pass.

## PR-06 — Synthetic replay and release acceptance evidence

- **Objective and code area.** Add a bounded, separately authorized synthetic audit replay path and tests in the private evaluation package, plus a milestone runbook in `docs/milestones`. Demonstrate replay from frozen inputs/clock and version-identifiable decisions through the internal boundary.
- **Prerequisite.** Merged PR-05 and an approved synthetic-only audit policy under D4 for access, minimum request facts and denied/revoked cases.
- **Non-goals.** Persisting real user evaluations, adopting a real approval service, operating on a private archive without permission, and public legal claims or recommendations.
- **Tests and evidence gate.** T40, T44, and repeated execution of the full matrix, including withdrawal/rollback and regression of M2 ordinary no-release behavior. Run `make check`, `make db-test`, `make api-test`, `make cds-test`, and the existing Chromium gate with disposable inputs where feasible. Record PASS / FAIL / NOT RUN.
- **Risk and rollback.** Historical conclusions could be reused as current authority or leak restricted references. Test audit purpose tags, denials and safe redaction. Disable the replay path and retain prior receipts under approved retention.
- **Done when** proof reproduction and live/replay isolation are independently reviewed, exact tests and limitations are recorded, and M2 NO-GO still holds.

## Acceptance decisions beyond synthetic engineering

| Gate | Evidence for human approval |
|---|---|
| Synthetic implementation start | Approve D1–D4 for PR-01 and give explicit coding authorization. Further approvals apply before expanding the slice. Merge of PR-00 alone records the design review. |
| Synthetic engineering completion | Every scoped proof, interval, consistency and denial scenario has deterministic evidence or an explicitly accepted exception. Existing Discovery and baseline gates remain green. Document audit, rollback, gaps and non-goals before review. |
| Private real-source evaluation | Separately approve D5, exact sources and usage rights, independently verified field/side, jurisdiction and rule evidence, coverage and freshness thresholds, real archive replay, and who may access the results. Close or explicitly disposition the applicable M2 blocker register items. Synthetic tests are engineering evidence only. |
| Real public legal claims | Separately approve D6 after M2 real-source acceptance and real serving authorization, authoritative M3 evidence for full-stay outcomes, and reviewed access and operational controls. Demonstrate withdrawal, bounded staleness and replay isolation. Real public serving remains NO-GO until explicitly approved. |

No proposed PR adds search, routing, ranking, occupancy, prediction, payment, a legal API or frontend recommendations. [M2 blocker register](M2_ACCEPTANCE_REPORT.md#blocker-register) · [Accepted ADRs](../architecture/DECISION_REGISTER.md)
