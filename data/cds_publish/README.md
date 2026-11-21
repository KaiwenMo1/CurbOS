# Atomic release publication

PR-04 registers private PR-03 candidates in PostgreSQL, verifies them through a separate login, freezes approved projections, and tests atomic pointer changes with synthetic fixtures. The installed synthetic enrollment ledger starts empty. The deployment still needs a separately approved real-data authorization and operator identity boundary.

## Register a private candidate

Apply Goose migrations through `00004` as a database administrator. Use PostgreSQL authentication and the existing local connection environment. The submitter uses a login with `curbos_publication_registrar`. Keep it separate from verifier, API, capture, reviewer, operator, and migration-owner credentials.

```sh
.venv/bin/python -m data.cds_publish \
  --batch-id "$batch_id" --scope-key "$scope_key" \
  --stage-dir "$staging_root/$batch_id" --candidate-dir "$candidate_root/$candidate_id" \
  --expected-report-sha "$candidate_report_sha256"
```

The registrar rechecks the stage against the database anchor and reproduces the PR-03 package before comparing its exact files and expected report digest. Registration inserts the private release, projections and QA in one transaction and leaves the release at `CANDIDATE`. The receipt returns a release ID, candidate report digest, projection plan digest, review locators and exclusion totals. An identical repeat reuses the release. A different plan or conflicting digest fails closed.

Projection preserves source IDs, hashes, Policy positions, Area links and explicit QA. It keeps Curb Zone geometry at `SOURCE_REPORTED`, with an empty physical resource link. The registrar excludes geometry that fails the PostGIS constraints or cannot round-trip to the source coordinate values. It drops only corresponding links and records an exclusion reason and count. Retain the private candidate and raw evidence alongside the database.

## Verify independently

In a separate session authenticated as a member of `curbos_publication_verifier`, rerun the command above with `--verify`. Use the intended PR-03 validation receipt and protected copies of the stage and candidate files. The verifier runs the same file verification, reproduces the projection plan, and submits the result. PostgreSQL matches the candidate and release IDs, lineage, report hash and database-computed plan hash against the sealed registration. It writes an immutable verification receipt with the authenticated login and time, then moves the release to `VALIDATED` in the same transaction. Exact retries return that receipt with the release's current state.

The verifier process reads the files. PostgreSQL enforces the role, separation of logins, evidence match, and atomic transition. It has no filesystem proof of the verification. Trust the verifier login only to the approved file-checking process and protect its credentials and file inputs from the registrar. A holder of verifier credentials can attest directly through SQL. A conflicting submission remains private and blocks reuse of that candidate identity pending investigation. The workflow provides no overwrite or approval shortcut.

## Lifecycle and independent evidence

| State | Required action or evidence |
|---|---|
| `CANDIDATE` | The registrar commits the private submission. Projections and attached evidence are sealed. |
| `VALIDATED` | An independently authenticated verifier attests to the exact submission after recomputing it from the files. |
| `APPROVED` | A reviewer distinct from the registrar and verifier binds approval to both returned digests and provides QA, license, scope, coverage, placement and exclusion evidence references. The database checks current source rights and scope approval, including a reviewed geometry that covers the projected Zone lines. |
| `FROZEN` | A reviewer freezes the approved release after the database rechecks the gate and scope geometry digest. The release row and all attached evidence remain immutable. |

Approval requires a nonempty license or rights reference for each exact artifact UUID. The reviewer provides an explicit reason for withholding every `REVIEW_REQUIRED` locator. The registrar never upgrades those records and stores their QA evidence. Source coordinates and rights fields are separate facts. Coverage and placement approvals are explicit evidence references, with the geometry check establishing source-line containment only.

The migrations grant function execution to separate registrar, verifier, reviewer and operator capabilities. The audit identity is the PostgreSQL session login. Pointer and audit inserts execute through a function owned by an executor role with no login or members. Use a least-privileged API login without publication membership or direct grants. The `curbos` owner used in disposable M1 examples is an administrative account. The database owner and superuser remain trusted to control DDL. Production authentication, review systems and source-rights decisions are later gates.

## Exercise synthetic pointer control

Use the disposable integration suite. It creates random, test-only login passwords and enrolls generated batches in the synthetic fixture ledger under a database administrator. Enrollment binds scope, batch, dataset and the stage hash, and the gate checks the synthetic source profile and artifact origins. The suite verifies that an unregistered or production-like candidate remains private even with approval-shaped evidence.

```sh
make cds-test PYTHON=.venv/bin/python
```

The reviewer calls `publication.approve_release(release_id, evidence_jsonb)` and `publication.freeze_release(release_id)`. The approval object uses `candidate_report_sha256`, `plan_sha256`, `qa_ref`, `rights_ref`, `scope_ref`, `coverage_ref`, `placement_ref` and `exclusion_ref`, plus the `artifact_rights` and `review_exclusions` objects.

An operator and reviewer are distinct authenticated logins, and activation requires an operator distinct from the registrar. With default PostgreSQL read-committed isolation, call `publication.change_pointer(scope, target_release, expected_version, action, reason, idempotency_key)` in one transaction:

- `ACTIVATE` points to an exact eligible frozen release in the scope.
- `ROLLBACK` points to a previously active, still eligible frozen release in the scope. Existing evidence is preserved.
- `WITHDRAW` uses a null target and clears an existing pointer in that scope. That release remains withdrawn in the append-only history. The action is available after rights or scope approval have been revoked.

An absent pointer starts at version zero. The successful request advances it once and returns the committed audit record. A stale version returns `PUBLICATION_VERSION_CONFLICT`. Replay with the same authenticated login and identical request returns the original audit outcome, even after a later pointer change. A changed request with a reused key returns `PUBLICATION_IDEMPOTENCY_CONFLICT`.

## Recovery and rollback

Retry connection failures using exactly the original request and idempotency key. The event verifies the result of an uncertain commit. For a version conflict, read the current pointer and independently review which exact target to request next. Any failed transaction rolls back both database changes. A revoked scope or source rights calls for explicit withdrawal and blocks eligibility for subsequent activation.

Product rollback changes the pointer to another eligible release. Schema Down is a separate operation for an isolated empty test database. It refuses to remove guards with publication registrations, and `00003` also protects fixture enrollment and audit. For disposable publication tests, discard the isolated project and volume. Capability group names are cluster-wide and Down leaves those group identities in place.

`00004` preserves the reviewed `00003` migration. Apply it with publication clients stopped. If a database already has registrations or active publication history from `00003`, the upgrade stops and preserves that history for independent review. An empty `00003` database can upgrade in place. Completing `00004` is required before granting publication logins access.
