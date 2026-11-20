# Private CDS evidence validation

M2 PR-03 consumes one registered Stage Schema v2 directory and prepares a private candidate package. PostgreSQL anchors the stage to its registered import batch and artifacts. The validator operates offline against a local PostgreSQL/PostGIS instance in a read-only transaction. Its result stays in the supplied private output root.

## Run

Use the same Linux or WSL development environment and pinned dependencies as CDS capture. Use a batch with status `STAGED` and a known, non-null `scope_key`. Pass that exact scope independently of the stage. The output root must be a separate directory outside Git with mode 0700, owned by the caller.

```sh
mkdir -m 700 "$validation_root"
.venv/bin/python -m data.cds_validate \
  --batch-id "$batch_id" --scope-key "$scope_key" \
  --stage-dir "$staging_root/$batch_id" --output-root "$validation_root"
```

Set `CURBOS_CAPTURE_DB_PORT` and supply `PGPASSWORD` through the environment as for capture. The CLI supports `--db-socket-dir` for local Unix socket access. Stage files must be private, read-only regular files. Use the existing version 2 stage from capture. Validation does not need source archives or access to the raw store.

The validator checks the report hash recorded in PostgreSQL before using the report. It verifies the deterministic batch ID, scope, one dataset across the staged roles, each component's registered artifact digest and size, the fixed file set, checksums, ordered record indices, geometry fingerprints, row counts, and quarantine records. The stage report supplies the declared CRS for this batch. The original artifact registration may contain an earlier capture's metadata for the same raw digest. A file is parsed from the same descriptor used to compute its checksum.

## QA decisions

- **Accepted evidence** passed this stage's automated checks. An otherwise valid Zone with consecutive duplicate vertices keeps its original line and an informational warning. PostGIS checks simplicity and validity on temporary geometry values. Source coordinates stay intact. A Zone's curb placement stays `UNVERIFIED` pending independent review.
- **Review required** includes unknown CRS or street side, missing road reference, conflicting source sides, non-simple lines, Area geometry limitations, and inconsistent or unresolved Area memberships. Empty Areas and unsupported geometry remain available as source records. Without DS12, Area membership resolution and the joint missing Area/road cohort are unassessed.
- **Excluded evidence** includes invalid or duplicate record IDs, unusable Policy forms, missing/ambiguous/invalid/unusable Zone Policy references, and unusable Zone shapes or explicitly unsupported Zone CRS. `policy_ref_status` measures identity resolution and `policy_parse_status` measures structural validation. Policy structure provides no evidence of legal permission, availability, or capacity.
- **Candidate links** join accepted records from the same batch. Policy links preserve source array positions. Area links require reciprocal membership and accepted endpoints. Area grouping supplies neither rule inheritance nor geographic coverage. Accepted evidence can stay private indefinitely. Review of source coherence, rights, independent curb placement, and publication eligibility belongs to later gates.

## Package format

A successful command emits a candidate UUID and report SHA-256. The UUID derives from the batch, scope, stage digest, artifact lineage, validation schema version, and geometry engine versions. The candidate directory contains:

| File | Contents |
|---|---|
| `evidence.ndjson` | One row for each original stage record in component and source order. Each row carries its disposition, sorted reasons, source index in the unchanged stage record, artifact ID, and batch and candidate IDs. |
| `quarantine.ndjson` | References to all review-required and excluded evidence rows. |
| `candidate.json` | The private candidate's lineage and accepted source IDs and indices, with same-candidate Policy and reciprocal Area links. |
| `report.json` | Per-role source and disposition totals, exclusion reason counts, reference and membership denominators, and output file digests. |
| `SHA256SUMS` | Digests for all four files, including the report. |

Every candidate and report has `public_eligible=false`. The dispositions sum to the input row count for each present role. Reason counts count rows per code and can overlap. Policy reference counts count source array entries, including repeats. Resolved-but-unusable is a subset of uniquely resolved. The report distinguishes affected Zone rows from distinct valid affected Zone IDs. Area counts distinguish source entries, unique directional pairs, reciprocal pairs, and reciprocal pairs omitted when an endpoint requires review or is excluded. A missing DS12 file yields null reconciliation counts.

## Recovery and limits

The validator uses an atomic, no-replace promotion from a scratch directory in the same output root. A retry rebuilds only its own interrupted scratch directory. An existing candidate is verified against deterministic output, and a mismatch fails closed. PostgreSQL remains read-only throughout validation. Undoing a validation run therefore involves only private local output. Preserve trusted input evidence and quarantine corrupt output before validating to a fresh private directory.

The implementation assumes a trusted PostgreSQL registry, local filesystem owner, and the pinned PostGIS stack for consistent topology results. Input files are bounded to 256 MiB each, with an additional 32 MiB ceiling for the stage report. Parsed stage records are held in memory. Retained raw byte integrity is established by capture. This validator anchors the resulting stage to PostgreSQL and does not repeat the raw capture. CI uses synthetic fixtures, including a validation run in a network namespace with a disposable PostgreSQL Unix socket. A real-archive regression requires an explicitly authorized local run.

Run the synthetic capture and validation suite in a disposable PostgreSQL project with `make cds-test PYTHON=.venv/bin/python`. Run formatting and lint with `make cds-lint RUFF=.venv/bin/ruff`.
