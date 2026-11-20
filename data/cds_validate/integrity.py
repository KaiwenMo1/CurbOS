"""Verify Stage Schema v2 against PostgreSQL's captured lineage."""

import os
import re
from collections import Counter
from contextlib import contextmanager
from hashlib import sha256

from data.cds_capture import files, stage
from data.cds_capture.manifest import (
    ROLES,
    CaptureError,
    batch_id_for_digest,
    canonical,
    digest,
    parse_json,
)

_REQUIRED_ROLES = {"zones", "policies"}
_MAX_STAGE_FILE = 256 * 1024 * 1024
_MAX_REPORT = 32 * 1024 * 1024
_QUARANTINE_FIELDS = (
    "role",
    "source_index",
    "source_id",
    "source_artifact_sha256",
    "issues",
)


def registered_lineage(connection, batch_id, scope_key):
    row = connection.execute(
        """
        SELECT b.scope_key, b.status, b.capture_manifest_sha256, b.validation_report_sha256,
               b.adapter_version, b.source_profile_version, s.scope_key
        FROM sources.import_batch b
        LEFT JOIN sources.publication_scope s ON s.scope_key = b.scope_key
        WHERE b.batch_id = %s
        """,
        (batch_id,),
    ).fetchone()
    if row is None:
        raise CaptureError("BATCH_NOT_FOUND")
    scope, status, capture_sha, stage_sha, adapter, profile, registered_scope = row
    if scope is None or scope != scope_key or registered_scope != scope_key:
        raise CaptureError("BATCH_SCOPE_MISMATCH")
    if status != "STAGED" or stage_sha is None:
        raise CaptureError("BATCH_NOT_STAGED")
    if batch_id != batch_id_for_digest(capture_sha):
        raise CaptureError("BATCH_IDENTITY_MISMATCH")

    artifacts = {}
    datasets = set()
    for (
        role,
        raw_role,
        artifact_id,
        dataset_id,
        raw_sha,
        size,
        uri,
        source_format,
    ) in connection.execute(
        """
            SELECT j.component_role, a.component_role, a.artifact_id, a.dataset_id,
                   a.content_sha256, a.byte_size, a.content_uri, a.source_format
            FROM sources.import_artifact j
            JOIN sources.raw_artifact a ON a.artifact_id = j.artifact_id
            WHERE j.batch_id = %s
            ORDER BY j.component_role, a.artifact_id
            """,
        (batch_id,),
    ):
        if (
            role not in ROLES
            or role in artifacts
            or raw_role != role
            or uri != f"cas+sha256:{raw_sha}"
            or source_format != "json"
            or size < 1
        ):
            raise CaptureError("ARTIFACT_LINEAGE_MISMATCH")
        artifacts[role] = {
            "artifact_id": str(artifact_id),
            "sha256": raw_sha,
            "byte_size": size,
        }
        datasets.add(dataset_id)
    if len(datasets) != 1 or not _REQUIRED_ROLES.issubset(artifacts):
        raise CaptureError("ARTIFACT_LINEAGE_MISMATCH")
    return {
        "batch_id": str(batch_id),
        "scope_key": scope_key,
        "dataset_id": str(next(iter(datasets))),
        "capture_manifest_sha256": capture_sha,
        "stage_report_sha256": stage_sha,
        "adapter_version": adapter,
        "source_profile_version": profile,
        "artifacts": artifacts,
    }


@contextmanager
def _regular(parent, name, limit):
    try:
        with files.regular(parent, name) as handle:
            info = os.fstat(handle.fileno())
            if info.st_uid != os.geteuid() or info.st_mode & 0o277:
                raise CaptureError("STAGE_FILE_NOT_PRIVATE_READ_ONLY")
            if info.st_size > limit:
                raise CaptureError("STAGE_FILE_TOO_LARGE")
            yield handle
    except OSError:
        raise CaptureError("STAGE_FILE_UNAVAILABLE_OR_UNSAFE") from None


def _read(parent, name, limit):
    with _regular(parent, name, limit) as handle:
        content = handle.read(limit + 1)
    if len(content) > limit:
        raise CaptureError("STAGE_FILE_TOO_LARGE")
    return content


def _json_object(raw, error):
    result = parse_json(raw, error)
    if not isinstance(result, dict) or canonical(result) != raw:
        raise CaptureError(error)
    return result


def _descriptor(item):
    return (
        isinstance(item, dict)
        and set(item) == {"sha256", "byte_size"}
        and isinstance(item["sha256"], str)
        and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is not None
        and type(item["byte_size"]) is int
        and 0 <= item["byte_size"] <= _MAX_STAGE_FILE
    )


def _ndjson(parent, name, spec):
    hasher = sha256()
    size = 0
    with _regular(parent, name, spec["byte_size"]) as handle:
        while line := handle.readline(spec["byte_size"] - size + 1):
            size += len(line)
            if size > spec["byte_size"]:
                raise CaptureError("STAGE_FILE_DIGEST_MISMATCH")
            hasher.update(line)
            yield _json_object(line, "INVALID_STAGE_RECORD")
    if size != spec["byte_size"] or hasher.hexdigest() != spec["sha256"]:
        raise CaptureError("STAGE_FILE_DIGEST_MISMATCH")


def _role_records(parent, role, component, spec, quarantine):
    records = []
    issue_counts = Counter()
    quarantined = 0
    for index, row in enumerate(_ndjson(parent, f"{role}.ndjson", spec)):
        payload = row.get("payload")
        source_id = payload.get(stage._IDS[role]) if isinstance(payload, dict) else None
        issues = row.get("issues")
        if (
            "payload" not in row
            or "source_id" not in row
            or type(row["source_id"]) is not type(source_id)
            or row["source_id"] != source_id
            or row.get("role") != role
            or row.get("source_artifact_sha256") != component["sha256"]
            or type(row.get("source_index")) is not int
            or row["source_index"] != index
            or not isinstance(issues, list)
            or any(not isinstance(issue, str) for issue in issues)
            or issues != sorted(set(issues))
            or row.get("status") != ("QUARANTINED" if issues else "PARSED")
        ):
            raise CaptureError("STAGE_RECORD_LINEAGE_MISMATCH", role)
        if role in ("zones", "areas"):
            geometry = payload.get("geometry") if isinstance(payload, dict) else None
            geom_sha = digest(canonical(geometry)) if geometry is not None else None
            if (
                row.get("source_geometry_sha256") != geom_sha
                or row.get("geometry_evidence") != "SOURCE_REPORTED"
            ):
                raise CaptureError("STAGE_GEOMETRY_LINEAGE_MISMATCH", role)
        if issues:
            quarantined += 1
            issue_counts.update(issues)
            if next(quarantine, None) != {key: row[key] for key in _QUARANTINE_FIELDS}:
                raise CaptureError("STAGE_QUARANTINE_MISMATCH")
        records.append(row)
    expected = {
        "record_count": len(records),
        "quarantined_count": quarantined,
        "parsed_count": len(records) - quarantined,
        "issue_counts": dict(issue_counts),
    }
    if any(
        type(component.get(key)) is not type(value) or component[key] != value
        for key, value in expected.items()
    ):
        raise CaptureError("STAGE_RECORD_COUNTS_MISMATCH", role)
    return records


def load_stage(parent, lineage):
    raw = _read(parent, "report.json", _MAX_REPORT)
    report_sha = digest(raw)
    if report_sha != lineage["stage_report_sha256"]:
        raise CaptureError("STAGE_REPORT_DIGEST_MISMATCH")
    report = _json_object(raw, "INVALID_STAGE_REPORT")
    if (
        type(report.get("stage_schema_version")) is not int
        or report["stage_schema_version"] != 2
    ):
        raise CaptureError("UNSUPPORTED_STAGE_SCHEMA")
    if (
        report.get("batch_id") != lineage["batch_id"]
        or report.get("capture_manifest_sha256") != lineage["capture_manifest_sha256"]
        or report.get("public_eligible") is not False
    ):
        raise CaptureError("STAGE_BATCH_IDENTITY_MISMATCH")

    components = report.get("components")
    artifacts = lineage["artifacts"]
    if (
        not isinstance(components, dict)
        or set(components) != set(artifacts)
        or report.get("areas_not_included") is not ("areas" not in artifacts)
    ):
        raise CaptureError("STAGE_COMPONENTS_MISMATCH")
    for role, artifact in artifacts.items():
        component = components[role]
        if (
            not isinstance(component, dict)
            or component.get("sha256") != artifact["sha256"]
            or type(component.get("byte_size")) is not int
            or component["byte_size"] != artifact["byte_size"]
            or component.get("source_format") != "json"
            or "source_crs" not in component
            or (
                component.get("source_crs") is not None
                and not isinstance(component["source_crs"], str)
            )
        ):
            raise CaptureError("STAGE_ARTIFACT_MISMATCH", role)

    names = {f"{role}.ndjson" for role in components} | {"quarantine.ndjson"}
    specs = report.get("stage_files")
    if (
        not isinstance(specs, dict)
        or set(specs) != names
        or not all(map(_descriptor, specs.values()))
        or set(os.listdir(parent)) != names | {"report.json", "SHA256SUMS"}
    ):
        raise CaptureError("STAGE_FILE_SET_MISMATCH")
    checksums = {name: spec["sha256"] for name, spec in specs.items()} | {
        "report.json": report_sha
    }
    expected_checksums = "".join(
        f"{sha}  {name}\n" for name, sha in sorted(checksums.items())
    ).encode("ascii")
    if _read(parent, "SHA256SUMS", 1024) != expected_checksums:
        raise CaptureError("STAGE_CHECKSUM_MANIFEST_MISMATCH")

    with_quarantine = _ndjson(parent, "quarantine.ndjson", specs["quarantine.ndjson"])
    try:
        rows = {
            role: _role_records(
                parent, role, components[role], specs[f"{role}.ndjson"], with_quarantine
            )
            for role in ROLES
            if role in components
        }
        if next(with_quarantine, None) is not None:
            raise CaptureError("STAGE_QUARANTINE_MISMATCH")
    finally:
        with_quarantine.close()
    quarantined = sum(
        bool(row["issues"]) for records in rows.values() for row in records
    )
    if (
        type(report.get("quarantined_count")) is not int
        or report["quarantined_count"] != quarantined
    ):
        raise CaptureError("STAGE_RECORD_COUNTS_MISMATCH")

    # Every record is read from the same file descriptor used for its digest.
    if set(os.listdir(parent)) != names | {"report.json", "SHA256SUMS"}:
        raise CaptureError("STAGE_FILE_SET_MISMATCH")
    return report, rows
