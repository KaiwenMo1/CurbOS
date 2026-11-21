"""Assess a private CDS batch without granting publication authority."""

import argparse
import os
import sys
from contextlib import ExitStack
from itertools import combinations
from pathlib import Path
from uuid import UUID

from data.cds_capture import database, files
from data.cds_capture.manifest import CaptureError, canonical, digest, parse_json
from data.cds_publish.__main__ import _projection_plan
from data.cds_validate.__main__ import (
    _VERSION as VALIDATOR_VERSION,
    _package_files,
    _path_pair,
    prepare,
)

from . import review, snapshot

_REVIEW_FILE_LIMIT = 1024 * 1024
_REPORT_VERSION = 2


def _read_private_json(path):
    with files.root(path.parent, private=True) as parent:
        with files.regular(parent, path.name) as handle:
            stat = os.fstat(handle.fileno())
            if stat.st_uid != os.geteuid() or stat.st_mode & 0o077:
                raise CaptureError("EVIDENCE_FILE_NOT_PRIVATE")
            raw = handle.read(_REVIEW_FILE_LIMIT + 1)
    if len(raw) > _REVIEW_FILE_LIMIT:
        raise CaptureError("EVIDENCE_FILE_TOO_LARGE")
    value = parse_json(raw, "INVALID_REVIEW_JSON")
    if not isinstance(value, dict):
        raise CaptureError("INVALID_REVIEW_JSON")
    return value


def _render(report):
    binding = report["subject"]
    source = report["source"]
    qa = report["qa"]
    coverage = report["coverage"]
    reference = qa["policy_references"]
    lines = [
        "# Private CDS readiness assessment",
        "",
        "**Decision** NO-GO for real publication.",
        "",
        "## Source identity",
        "",
        f"- Dataset ID `{report['lineage']['dataset_id']}`",
        f"- Publisher and dataset `{source['publisher_key']}` / `{source['dataset_key']}`",
        f"- Scope and Batch `{binding['scope_key']}` / `{binding['batch_id']}`",
        f"- Candidate `{binding['candidate_id']}`",
        "",
        "## Verified technical integrity and quarantine",
        "",
        "The retained artifact bytes, database-anchored Stage, exact candidate, and projection were verified.",
    ]
    for role, group in qa["roles"].items():
        dispositions = group["dispositions"]
        lines.append(
            f"- {role}: {group['input_rows']} source rows, {dispositions['ACCEPTED']} accepted, "
            f"{dispositions['REVIEW_REQUIRED']} review required, {dispositions['EXCLUDED']} excluded."
        )
    lines += [
        f"- Policies: {reference['missing_ids']} missing reference entries and "
        f"{reference['resolved_but_unusable']} resolved but unusable entries "
        f"of {reference['declared_entries']} declared references.",
        f"- DS12 membership assessed: {'yes' if qa['area_membership']['assessed'] else 'no'}.",
        f"- Projected Zone lines: {qa['projection']['projected']['zones']}.",
        f"- Registry status: {report['registration']['status']}.",
        "",
        "## Rights, coverage and placement",
        "",
        f"- Registry rights status: {source['registered_rights_status']}. This is a database observation.",
        f"- Boundary comparison: {coverage['comparison_status']}. The comparison uses projected Zone lines as its denominator.",
        "- Curb lines remain source-reported. Area membership is a grouping signal.",
        "",
        "## Supplied evidence assertions",
        "",
    ]
    claims = [
        (name, item)
        for name, item in report["checklist"].items()
        if item["declared_state"] is not None
    ]
    for name, item in claims:
        ref = item["evidence_ref"] or "none"
        lines.append(
            f"- `{name}`: declared `{item['declared_state']}`, reference `{ref}`, verification `UNVERIFIED`."
        )
    if not claims:
        lines.append("- No checklist items were supplied.")
    if report["withholding_assertions"]:
        lines.append(
            "- Supplied withholding references are retained as unverified assertions in `readiness.json`."
        )
    lines += [
        "",
        "## Independent approvals and publication authorization",
        "",
        "- Independent approval verification is `NOT_ASSESSED`. Verification of the record, reviewer identity, authority, and independence is deferred.",
        "- Publication authorization is missing. The report confers no authority to publish.",
        "",
        "## Parking legality and publication security",
        "",
        "- Legal backing, posted signs, temporary restrictions, permits and full-stay applicability remain unverified.",
        "- Parking legality, occupancy, availability and physical fit are UNKNOWN.",
        "- The operator workflow and serving paths remain synthetic-only. This assessment carries no activation authority.",
        "",
        "## Outcomes and unresolved requirements",
        "",
    ]
    for name, outcome in report["outcomes"].items():
        lines.append(f"- **{name}** {outcome['status']}")
        lines.extend(
            f"  - `{reason['code']}` · `{reason['evidence_ref']}`"
            for reason in outcome["reasons"]
        )
    lines += [
        "",
        "## Next engineering and review actions",
        "",
        "- Reconcile the exact source bundle's rights and attribution, review the bounded scope and field placement evidence, and document withheld records.",
        "- Bring the evidence and a separate production authorization and withdrawal plan to independent review.",
        "- Keep the candidate private. The recommendation remains **NO-GO**.",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _publish_report(root, report):
    encoded = canonical(report)
    fingerprint = digest(encoded)
    scratch = f".{fingerprint}.partial"
    documents = {"readiness.json": encoded, "READINESS_REPORT.md": _render(report)}
    documents["SHA256SUMS"] = "".join(
        f"{digest(content)}  {name}\n" for name, content in sorted(documents.items())
    ).encode("ascii")
    with files.lock(root, f".{fingerprint}.lock"):
        files.remove_stage_temporary(root, scratch)
        if files.present(root, fingerprint):
            with files.directory(root, (fingerprint,)) as retained:
                stat = os.fstat(retained)
                if stat.st_uid != os.geteuid() or stat.st_mode & 0o077:
                    raise CaptureError("REPORT_PACKAGE_NOT_PRIVATE")
                if set(os.listdir(retained)) != set(documents) or any(
                    files.fingerprint(retained, name) != (digest(content), len(content))
                    for name, content in documents.items()
                ):
                    raise CaptureError("RETAINED_REPORT_MISMATCH")
            return fingerprint

        os.mkdir(scratch, 0o700, dir_fd=root)
        try:
            with files.directory(root, (scratch,)) as directory:
                for name, content in documents.items():
                    files.write_file(directory, name, (content,))
                os.fsync(directory)
            files.promote(root, scratch, fingerprint)
        finally:
            files.remove_stage_temporary(root, scratch)
    return fingerprint


def run(
    batch_id,
    scope_key,
    artifact_root,
    stage_dir,
    candidate_dir,
    expected_report_sha,
    output_root,
    *,
    evidence_file=None,
    baseline_file=None,
    db_socket_dir=None,
):
    if not isinstance(expected_report_sha, str) or not review.SHA256.fullmatch(
        expected_report_sha
    ):
        raise CaptureError("INVALID_CANDIDATE_REPORT_DIGEST")
    if not os.environ.get("PGUSER"):
        raise CaptureError("ASSESSMENT_DATABASE_ROLE_REQUIRED")
    roots = [
        files.absolute(path)
        for path in (artifact_root, stage_dir, candidate_dir, output_root)
    ]
    for path in roots[:-1]:
        _path_pair(path, roots[-1])
    if any(
        left.is_relative_to(right) or right.is_relative_to(left)
        for left, right in combinations(roots, 2)
    ):
        raise CaptureError("OVERLAPPING_ASSESSMENT_ROOTS")
    review_paths = [
        files.absolute(path) if path is not None else None
        for path in (evidence_file, baseline_file)
    ]
    if any(
        path.is_relative_to(root)
        for path in review_paths
        if path is not None
        for root in roots
    ):
        raise CaptureError("OVERLAPPING_ASSESSMENT_ROOTS")
    evidence, baseline = (
        _read_private_json(path) if path is not None else None for path in review_paths
    )

    with ExitStack() as stack:
        raw, staged, package, output = [
            stack.enter_context(files.root(path, private=True)) for path in roots
        ]
        if len(
            {
                (info.st_dev, info.st_ino)
                for info in map(os.fstat, (raw, staged, package, output))
            }
        ) != len(roots):
            raise CaptureError("OVERLAPPING_ASSESSMENT_ROOTS")
        with database.transaction(db_socket_dir) as connection:
            connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            connection.execute("SET LOCAL TIME ZONE 'UTC'")
            lineage, candidate_id, records, candidate, summary = prepare(
                connection, batch_id, scope_key, staged
            )
            if roots[2].name != candidate_id:
                raise CaptureError("CANDIDATE_IDENTITY_MISMATCH")
            actual = _package_files(
                package, lineage, candidate_id, records, candidate, summary, True
            )
            if actual != expected_report_sha:
                raise CaptureError("CANDIDATE_REPORT_DIGEST_MISMATCH")
            snapshot.verify_artifacts(raw, lineage)
            source = snapshot.source_registry(connection, lineage)
            plan = _projection_plan(connection, records, candidate, summary)
            coverage = snapshot.coverage(connection, scope_key, plan["zones"])
            registration = snapshot.registration(
                connection, lineage, candidate_id, actual, plan
            )

        subject = {
            "batch_id": lineage["batch_id"],
            "scope_key": scope_key,
            "stage_report_sha256": lineage["stage_report_sha256"],
            "candidate_id": candidate_id,
            "candidate_report_sha256": actual,
        }
        items, claim, withheld = review.checklist(
            evidence,
            subject,
            coverage["boundary_sha256"],
            plan["review_required"],
        )
        qa = review.qa_summary(records, summary, plan, lineage)
        basis = {
            "artifact_sha256": {
                role: a["sha256"] for role, a in lineage["artifacts"].items()
            },
            "adapter_version": lineage["adapter_version"],
            "source_profile_version": lineage["source_profile_version"],
            "stage_schema_version": 2,
            "validation_schema_version": VALIDATOR_VERSION,
            "geometry_engine": lineage["geometry_engine"],
            "metric_schema_version": review.METRIC_SCHEMA_VERSION,
        }
        report = {
            "assessment_schema_version": _REPORT_VERSION,
            "readiness_policy_version": review.POLICY_VERSION,
            "state": "ASSESSMENT_COMPLETE",
            "recommendation": "NO_GO",
            "public_eligible": False,
            "subject": subject,
            "lineage": lineage,
            "source": source,
            "registration": registration,
            "qa": qa,
            "coverage": coverage,
            "checklist": items,
            "withholding_assertions": {
                locator: {"evidence_ref": ref, "verification_status": "UNVERIFIED"}
                for locator, ref in withheld.items()
            },
            "independent_approval_verification": {
                "status": "NOT_ASSESSED",
                "reason": "AUTHORITATIVE_ATTESTATION_VERIFICATION_DEFERRED",
            },
            "placement": {
                "proposed_claim": claim,
                "projected_geometry_provenance": "SOURCE_REPORTED",
                "projected_geometry_type": "LineString",
                "physical_alignment_type": "UNKNOWN",
                "projected_independently_verified_count": 0,
                "projected_zone_denominator": len(plan["zones"]),
                "physical_placement": "UNKNOWN",
                "coordinate_transformation_applied": False,
                "independent_placement_requirement": {
                    "state": "NOT_APPLICABLE"
                    if claim == "SOURCE_REPORTED_ONLY"
                    else items["independent_placement"]["verification_status"],
                    "reason": "SOURCE_REPORTED_ONLY_CLAIM"
                    if claim == "SOURCE_REPORTED_ONLY"
                    else "CLAIM_REQUIRES_INDEPENDENT_PLACEMENT",
                },
            },
            "parking_evidence": dict.fromkeys(
                (
                    "authoritative_legal_backing",
                    "posted_signs",
                    "temporary_restrictions",
                    "permits",
                    "full_stay_applicability",
                    "parking_legality",
                    "occupancy",
                    "availability",
                    "physical_fit",
                ),
                "UNKNOWN",
            ),
            "publication_controls": {
                "production_publication_process": "BLOCKED",
                "real_world_authorization": "BLOCKED",
                "real_data_serving": "BLOCKED",
                "real_withdrawal_rehearsal": "NOT_ASSESSED",
            },
            "reproducibility": {
                "tool_version": _REPORT_VERSION,
                "comparison_basis": basis,
                "evidence_sha256": digest(canonical(evidence))
                if evidence is not None
                else None,
                "baseline_sha256": digest(canonical(baseline))
                if baseline is not None
                else None,
                "database_snapshot": "REPEATABLE_READ_READ_ONLY",
            },
            "historical_comparison": review.compare_history(baseline, basis, qa),
            "outcomes": review.outcomes(items, source, coverage, claim, plan, withheld),
        }
        key = _publish_report(output, report)
    return {
        "state": "ASSESSMENT_COMPLETE",
        "report_directory": key,
        "report_sha256": key,
        "recommendation": "NO_GO",
        "public_eligible": False,
    }


class _Arguments(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, '{"code":"INVALID_ARGUMENTS","state":"FAILED"}\n')


def main():
    parser = _Arguments(description=__doc__)
    parser.add_argument("--batch-id", required=True, type=UUID)
    parser.add_argument("--scope-key", required=True)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--stage-dir", required=True, type=Path)
    parser.add_argument("--candidate-dir", required=True, type=Path)
    parser.add_argument("--expected-report-sha", required=True)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--evidence-file", type=Path)
    parser.add_argument("--baseline-file", type=Path)
    parser.add_argument("--db-socket-dir", type=Path)
    try:
        result = run(**vars(parser.parse_args()))
    except (CaptureError, OSError) as error:
        code = (
            error.code
            if isinstance(error, CaptureError)
            else "ASSESSMENT_FILESYSTEM_FAILURE"
        )
        failure = {"state": "FAILED", "code": code, "public_eligible": False}
        if isinstance(error, CaptureError) and error.role:
            failure["role"] = error.role
        sys.stderr.write(canonical(failure).decode("ascii"))
        return 1
    sys.stdout.write(canonical(result).decode("ascii"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
