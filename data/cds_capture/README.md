# Offline CDS capture and staging

M2 PR-02 reads local Code the Curb DS13 Zones and DS11 Policies JSON files declared in a version 1 manifest. DS12 Areas can be included explicitly. The CLI works with extracted files and does not open a ZIP archive or resolve source URIs. [Manifest schema](manifest.schema.json)

Use Linux or WSL with Python 3.12 and a local filesystem that supports advisory file locks, directory fsync, and atomic no-replace rename. Keep the private output roots on that filesystem and outside Git checkouts. Install dependencies before running offline.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r data/cds_capture/requirements.txt
```

## Preflight and capture

Prepare four separate, non-nested roots. The input root contains the manifest and extracted files. The artifact, staging and report roots must exist, be owned by the caller, and have mode 0700. The CLI rejects symlinked path components and reads each input from one verified regular-file descriptor. Each component is limited to 128 MiB, and the manifest is limited to 128 KiB. This adapter parses the bounded bundle in memory.

```sh
.venv/bin/python -m data.cds_capture \
  --manifest manifest.json --input-root "$input_root" \
  --artifact-root "$artifact_root" --staging-root "$staging_root" \
  --report-root "$report_root" --dry-run
```

Require both `zones` and `policies`. Declare `areas` only if its file is present. Use a relative input path, exact lowercase SHA-256 and byte count, a real catalog URI and original component URI from verified metadata, and a UTC capture timestamp with a `Z` suffix. Declare `source_as_of` and `timestamp_unit` when supported by the manifest evidence. A numeric source `last_updated` is preserved with its declared or inferred unit. If no unit is declared, magnitudes at or above `100000000000` are treated as milliseconds and smaller values as seconds, with the inference recorded. Missing and invalid timestamps get reason codes. Rights can be `UNKNOWN` or `REVIEW_REQUIRED`. Keep credentials and signed URLs out of the manifest.

With separate approval to inspect real archives, manually verify the ZIP SHA-256 against the approved handoff inventory and extract only the selected component files into the input root. Copy the approved inventory CSV there and add `--archive-inventory SOURCE_ARCHIVE_INVENTORY.csv` to the dry run. The CLI checks each selected role, entry digest and length against the inventory, then verifies the extracted bytes. The same gate is tested with invented entries. No real archive is used by default.

For an authorized local capture, apply the existing Goose migrations and remove `--dry-run`. Set `CURBOS_CAPTURE_DB_PORT` to the local PostgreSQL port and supply `PGPASSWORD` through the environment when PostgreSQL requires it. The database and role default to `curbos` and can be selected with `PGDATABASE` and `PGUSER`. The CLI uses loopback TCP or an explicit local `--db-socket-dir` and rejects ambient database routing via `PGSERVICE` or `PGHOSTADDR`. A non-null manifest `scope_key` must already exist. The CLI does not approve or create scopes. Local dry runs write a preflight report and require no database.

## State and recovery

- **Raw artifacts** live at `<artifact-root>/<sha256>` and are registered as `cas+sha256:<digest>`. The tool verifies exact bytes, syncs and atomically promotes a read-only file, then verifies retained evidence on replay. Locks coordinate writers within each store. They cannot prevent modification by its owner or an administrator.
- **Provenance registration** is one PostgreSQL transaction. The canonical semantic digest covers manifest version, source identity, scope, adapter/profile versions and component content, CRS, format, and declared as-of/unit. Paths, origin and rights annotations, and capture time are retained in private evidence reports. They do not split otherwise identical captures. A deterministic batch UUID and the existing batch uniqueness constraints arbitrate concurrent registration. After a conflict, the tool locks the existing row and verifies its capture identity. Reused dataset and artifact rows keep their original provenance. Component roles and IDs are checked on replay.
- **Private staging** lives at `<staging-root>/<batch-id>/`. Each role’s NDJSON records follow original array order, with zero-based source positions, sorted JSON keys, exact parsed decimal values and a source artifact digest. Geometry hashes describe the source payload. Quarantine points to the original staged row and raw artifact by role, index and digest. `report.json` records denominators, missing references, typed QA and source metadata. `SHA256SUMS` covers the stage report and all NDJSON files. A separate private evidence report retains the manifest's original relative paths and origin metadata. Successful stdout contains only state, identifiers and a relative report filename.
- **Status** advances from `CAPTURED` to `STAGED` once the complete directory and evidence report are durable. The existing batch report-digest field stores the private stage report hash. A fatal preflight or registration failure leaves no new batch. A crash after registration leaves `CAPTURED` until a retry verifies the stage and records its digest. Retries clean scratch for the same capture or digest and never replace conflicting retained evidence. A rejected retry preserves any prior successful batch status. Bump the adapter version for changes to staging semantics. Back up the database and both private stores together.

The tool writes QA to local files and creates no database QA, release, pointer or projection rows. All reports have `public_eligible=false`, including batches with zero quarantines. Source geometry and resolved policy IDs provide no evidence of field accuracy, legal coverage or vacancy.

## Zone policy QA

`policy_ref_status` measures ID resolution. `COMPLETE` means every ID in a nonempty reference list matches exactly one Policy in the batch. Missing, duplicate or invalid references make it `INCOMPLETE`. An absent or empty list is `UNASSESSED`.

`policy_parse_status` is `PASSED` when every reference resolves uniquely and every matched record passed PR-02's structural checks. It is `FAILED` when any uniquely resolved Policy is quarantined, including when the Zone also has unresolved references. Those Zones receive `POLICY_REFERENCE_UNUSABLE`. In other cases where the references cannot all be assessed, the parse status is `UNASSESSED`. A structural pass establishes only that the adapter accepts the record shape. Legal meaning and public eligibility require separate review.

Stage schema version 2 records `zone_policy_parse_status_counts` in `report.json` alongside the existing missing-reference and quarantine totals. For a manifest with a retained version 1 stage, use a new manifest `adapter_version` to create a separate batch with the revised QA.

For deeper offline QA and private candidate preparation, pass the registered Stage Schema v2 directory to the [evidence validator](../cds_validate/README.md).

## Reproduce synthetic checks

```sh
.venv/bin/python -m pip install -r data/cds_capture/requirements-test.txt
make cds-unit PYTHON=.venv/bin/python
make cds-lint RUFF=.venv/bin/ruff
make cds-test PYTHON=.venv/bin/python
```

The disposable Compose test covers T01–T21 with synthetic inputs. T19 runs the full CLI in a network namespace with a Unix socket bound from the disposable database. T22 includes a synthetic inventory replay and leaves real-archive validation to an approved manual run. T23 runs through `make db-test`, `make api-test`, `make e2e-test` and `make check`. T24 uses the pinned Python dependencies, Ruff and generated synthetic fixtures. CI installs test dependencies before the offline capture test.
