# Private CDS real-source readiness

PR-07 produces a private go/no-go assessment for one exact batch and scope. The approved Master Pack requires independent legal and rights review, field placement samples, reviewed coverage, and human approval for real publication. The tool verifies technical integrity and records submitted assertions for later review. The current authorization covers synthetic assessments. The report's real-publication recommendation is always `NO_GO`.

## Run on separately authorized private evidence

Use an already captured PR-02 batch and the PR-03 private validation package. Keep the raw content-addressed store, stage, candidate package, and assessment output in separate private Linux directories outside Git. The Stage directory is the batch's exact Stage Schema v2 directory. The candidate directory is named for the candidate UUID. Obtain the expected candidate report SHA-256 from the validation receipt. Keep that receipt independently of the candidate directory.

A private database administrator can provision a separate login with no write or publication memberships. On the intended local assessment database, grant only the columns and pure geometry function listed in the reader script. This login reads private registry data and belongs in the private database environment. Keep the credentials in the operator's protected local credential mechanism. Use the database administrator session only for provisioning. [Reader permissions](reader_privileges.sql)

```sh
# In the administrator session connected to the intended private database
psql -X -v ON_ERROR_STOP=1 -v reader="$assessment_reader" -f data/cds_readiness/reader_privileges.sql

# In the private assessment session
umask 077
mkdir -p "$assessment_output_root"
export PGUSER="$assessment_reader"
export CURBOS_CAPTURE_DB_PORT="$assessment_db_port"
.venv/bin/python -m data.cds_readiness \
  --batch-id "$batch_id" --scope-key "$scope_key" \
  --artifact-root "$artifact_root" --stage-dir "$staging_root/$batch_id" \
  --candidate-dir "$candidate_root/$candidate_id" \
  --expected-report-sha "$candidate_report_sha256" --output-root "$assessment_output_root"
```

The command uses the existing loopback PostgreSQL connection settings and also accepts `--db-socket-dir`. Install the existing pinned Python requirements from `data/cds_capture/requirements.txt`. The assessment uses one PostgreSQL `REPEATABLE READ, READ ONLY` transaction. It reuses the PR-03 verifier against the registered Stage report anchor and checks the bytes and sizes of each retained raw CAS object. It recomputes the PR-04 projection without registering it and matches any registration against the exact candidate, report, lineage, and plan digest. PostgreSQL, the original capture authority, and the owner of the private stores remain trusted. [Capture runbook](../cds_capture/README.md) · [Validation runbook](../cds_validate/README.md) · [Publication runbook](../cds_publish/README.md)

## Evidence checklist

An omitted checklist leaves the required items unknown. Supply an optional `--evidence-file` to retain a reviewer's claims alongside the technical evidence. It must be a JSON object owned by the assessor with no group or world access. Put it in a private directory outside the four stores and outside Git.

| Field | What the reviewer supplies |
|---|---|
| `schema_version` | Integer `1`. |
| `binding` | The exact `subject` from an initial successful assessment. It binds batch, scope, stage digest, candidate ID, and candidate report digest. |
| `items` | A map from checklist key to an object with `state` and `evidence_ref`. Use `UNKNOWN` with a null reference, or submit an `APPROVED` or `BLOCKED` assertion with an opaque `evidence:<id>` reference. |
| `reviewed_boundary_sha256` | Required when declaring `independent_coverage` to be `APPROVED`. It must match the exact stored geometry digest. The match binds the assertion to the boundary bytes. |
| `placement_claim` | Optional. Defaults to `SOURCE_REPORTED_ONLY`. The `INDEPENDENTLY_VERIFIED` claim requires independent review and stays blocked for this projection, which is source-reported. |
| `withheld_records` | Optional mapping from an exact review-required locator such as `zones:<index>` to the supplied withholding reference. The tool keeps it as an unverified assertion. |

Rights keys are `publisher_identity`, `distribution_origin`, `acquisition_date`, `published_terms`, `private_storage`, `transformation`, `geometry_redistribution`, `attribution`, `commercial_and_public_use_restrictions`, `downstream_map_display`, and `revocation_and_updates`. Review each exact component through its private provenance reference and verify that the rights decision covers the proposed use. Catalog and distribution URIs appear as hashes in the report. Component acquisition times are registry facts and do not establish rights. Keep terms, license versions, signed decisions, and any required attribution text in the private review record.

Other keys are `source_qa_decisions`, `independent_coverage`, and `independent_placement`. The report retains each supplied state as `declared_state` and preserves its exact `evidence_ref`. A supplied item has `verification_status=UNVERIFIED`. An omitted item has a null declaration and `verification_status=NOT_ASSESSED`. The checker validates subject binding and reference syntax. Independent verification of record existence, identity, authority, and separation of duties requires a separately approved attestation design. The report records that verification as `NOT_ASSESSED`. Database rights and scope review fields are reported as registry observations. The placement requirement is `NOT_APPLICABLE` for a source-reported-only claim while physical placement remains `UNKNOWN`.

## Read the outcomes and denominators

- **Technical readiness** passes after replaying the authenticated private batch, stage, candidate, and projection. Integrity failures return a nonzero exit with a reason code and leave no final report. A completed assessment may legitimately contain exclusions or an empty projection.
- **Evidence readiness** remains `BLOCKED` because independent approvals cannot be verified in this slice. The report identifies additional gaps for source QA, boundary and field review, dispositions, representability, and geometric containment. An `APPROVED` assertion with a matching digest and reference leaves that item unverified.
- **Publication readiness** remains blocked by the production authorization and serving boundaries, any known or unknown rights gaps, and an unassessed real withdrawal rehearsal. Synthetic publication and withdrawal tests are engineering evidence only. The assessment creates no release, change to rights, pointer movement, or audit event.
- **Parking evidence** remains unknown for legality, occupancy, availability, and fit. DS11 Policy parsing and same-batch references establish structural coherence. Posted signs, temporary restrictions, permits, authoritative legal backing, and full-stay applicability require separate evidence.

Read the report's `qa.roles` for source-row denominators and dispositions. Reason counts can overlap. The affected-row references contain normalized IDs where valid, the zero-based source index, and the exact artifact ID. Invalid source IDs and arbitrary text stay in private Stage records. Policy reference metrics count both entries and affected Zone rows, and preserve the difference between absent, ambiguous and structurally unusable Policy IDs. Rule usage counts describe recorded activity labels on rule entries. They establish no legal semantics. DS12 directional counts distinguish declared entries, valid unique pairs, reciprocal pairs, and one-sided relationships. An absent DS12 component yields `NOT_ASSESSED` with null Area-specific measurements.

Coverage compares the declared scope's stored geometric boundary to **projected Zone lines**. Counts distinguish fully covered lines, lines intersecting but not fully covered, and disjoint lines. Coverage and projection exclusions have record-level references. A scope without a stored boundary yields null measured counts. Artifact-level CRS, approximate road references, repeated vertices, street-side QA, and geometry representability do not establish physical alignment.

## Historical audit comparison

The historical audit described roughly 22,794 Zones, 108 Policies, 18 missing Policy references in 17 Zones, 1,044 repeated-vertex Zones, 49 Zones lacking both Area membership and OSM reference, 4 Zones without street-side data, 9 Areas, and roughly 45,862 Area–Zone relationships. It also documented the empty Whole Area geometry and the Automotus Cameras MultiLineString. These are observations from a prior source audit. They are not v1 thresholds or results from this implementation.

An optional private `--baseline-file` has `schema_version: 1`, an opaque `evidence_ref`, a `basis` object, a `metrics` map and an `areas` map. Populate `basis` with the provenance of the historical audit, using the shape of `reproducibility.comparison_basis`. Comparison requires exact component SHA-256 hashes and matching adapter, source profile, Stage, validator, geometry-engine and metric schema versions. Archive-level hashes alone cannot establish this match. Supply only counts with the same denominators as `qa.comparable_metrics`. Use audited normalized Area UUIDs as keys in `areas`, with `geometry_type` and `empty_geometry` values. Investigate differing counts against the exact snapshot, QA version, and denominator. Unavailable or unmatched audit evidence yields `NOT_ASSESSED`.

## Output and recovery

The command emits only a private report receipt. A final directory named for the SHA-256 of `readiness.json` contains that JSON, `READINESS_REPORT.md`, and `SHA256SUMS`. A complete blocked report exits zero. An integrity or filesystem failure exits nonzero. Reports intentionally omit raw records, full source payloads, credentials, physical geometry coordinates and approval actors. Keep all generated reports outside Git. The corrected output uses schema and readiness policy v2. Checklist and historical baseline input retain v1, as do comparison metrics. Preserve older private reports for audit and rerun the same inputs to obtain the corrected evidence outcome and declaration labels.

The tool writes and syncs both files in private scratch and atomically promotes the whole directory. Repeating the same snapshot and inputs verifies and reuses the exact bytes. Rerun with the same arguments after interruption. A conflicting final report is kept for investigation and must never be repaired in place. A new verified snapshot or checklist revision produces a new report directory. Rollback is retaining the previous private report and ceasing use of the new tool. There are no publication or database changes to reverse.

Use `make cds-test` for synthetic verification. Existing publication tests exercise registrar/verifier/reviewer separation and reject a production-like synthetic record even when a test administrator adds an enrollment row. The normal API denies synthetic visibility, and the pinned-read integration suite exercises scope withdrawal and historical pins. The assessor itself performs no activation, authority transition or live source fetch.
