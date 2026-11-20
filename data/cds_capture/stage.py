"""Parse the bounded CDS shape and write a deterministic private stage."""

import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from . import files
from .manifest import ROLES, CaptureError, canonical, digest, parse_json

_IDS = {"zones": "curb_zone_id", "policies": "curb_policy_id", "areas": "curb_area_id"}


@dataclass(frozen=True)
class Snapshot:
    entry: dict
    raw: bytes
    records: list
    metadata: dict
    timestamp: dict


def _timestamp(metadata, declared):
    value = metadata.get("last_updated")
    result = {"raw": value, "unit": declared, "unit_origin": None, "utc": None}
    if declared:
        result["unit_origin"] = "manifest"
    if value is None:
        return result | {"reason": "MISSING_SOURCE_TIMESTAMP"}
    if type(value) not in (int, Decimal):
        return result | {"reason": "INVALID_SOURCE_TIMESTAMP"}
    if declared is None:
        result["unit"] = "milliseconds" if abs(value) >= 100_000_000_000 else "seconds"
        result["unit_origin"] = "inferred"
    scale = 1000 if result["unit"] == "milliseconds" else 1
    if not 0 <= value < 253_402_300_800 * scale:
        return result | {"reason": "SOURCE_TIMESTAMP_OUT_OF_RANGE"}
    try:
        # Preserve the original numeric value independently of the display conversion.
        utc = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
            seconds=float(value / scale)
        )
    except OverflowError:
        return result | {"reason": "SOURCE_TIMESTAMP_OUT_OF_RANGE"}
    return result | {"utc": utc.isoformat().replace("+00:00", "Z"), "reason": None}


def load_snapshot(entry, raw):
    role = entry["role"]
    if len(raw) != entry["byte_size"]:
        raise CaptureError("COMPONENT_LENGTH_MISMATCH", role)
    if digest(raw) != entry["sha256"]:
        raise CaptureError("COMPONENT_DIGEST_MISMATCH", role)
    payload = parse_json(raw, "INVALID_COMPONENT_JSON", role)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise CaptureError("INVALID_COMPONENT_ENVELOPE", role)
    if set(data[0]).intersection(ROLES) != {role} or not isinstance(
        data[0][role], list
    ):
        raise CaptureError("COMPONENT_ROLE_MISMATCH", role)
    metadata = {key: value for key, value in payload.items() if key != "data"}
    return Snapshot(
        entry,
        raw,
        data[0][role],
        metadata,
        _timestamp(metadata, entry.get("timestamp_unit")),
    )


def _uuid(value):
    if not isinstance(value, str) or len(value) != 36:
        return None
    try:
        normalized = str(UUID(value))
    except ValueError:
        return None
    return normalized if normalized == value.lower() else None


def _position(position):
    return (
        isinstance(position, list)
        and len(position) == 2
        and all(type(number) in (int, Decimal) for number in position)
        and -180 <= position[0] <= 180
        and -90 <= position[1] <= 90
    )


def _zone_geometry(geometry):
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        return ["ZONE_GEOMETRY_NOT_LINESTRING"]
    coordinates = geometry.get("coordinates")
    if coordinates == []:
        return ["ZONE_GEOMETRY_EMPTY"]
    if not isinstance(coordinates, list) or not all(map(_position, coordinates)):
        return ["ZONE_GEOMETRY_INVALID_COORDINATES"]
    issues = []
    if len({tuple(point) for point in coordinates}) < 2:
        issues.append("ZONE_GEOMETRY_DEGENERATE")
    if any(left == right for left, right in zip(coordinates, coordinates[1:])):
        issues.append("ZONE_GEOMETRY_REPEATED_VERTEX")
    return issues


def _area_geometry(geometry):
    if geometry is None:
        return ["AREA_GEOMETRY_MISSING"]
    if not isinstance(geometry, dict):
        return ["AREA_GEOMETRY_INVALID"]
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        return ["AREA_GEOMETRY_INVALID"]
    if coordinates == []:
        return ["AREA_GEOMETRY_EMPTY"]
    if geometry.get("type") == "MultiLineString":
        return ["AREA_GEOMETRY_MULTILINESTRING"]
    if geometry.get("type") not in ("Polygon", "MultiPolygon"):
        return ["AREA_GEOMETRY_UNSUPPORTED"]
    return []  # Area coordinate/topology and coverage review belong to PR-03.


def _policy_supported(payload):
    rules = payload.get("rules")
    return (
        isinstance(rules, list)
        and bool(rules)
        and all(
            isinstance(rule, dict)
            and isinstance(rule.get("activity"), str)
            and bool(rule["activity"].strip())
            and isinstance(rule.get("user_classes", []), list)
            and all(isinstance(item, str) for item in rule.get("user_classes", []))
            for rule in rules
        )
    )


def _identities(snapshot):
    field = _IDS[snapshot.entry["role"]]
    return Counter(
        normalized
        for record in snapshot.records
        if isinstance(record, dict)
        and (normalized := _uuid(record.get(field))) is not None
    )


def _zone_policies(payload, policy_ids, usable_policy_ids):
    raw = payload.get("curb_policy_ids")
    assessment = {
        "policy_ref_status": "UNASSESSED",
        "policy_parse_status": "UNASSESSED",
        "missing_policy_refs": [],
    }
    if raw is None or raw == []:
        return assessment, ["POLICY_REFERENCES_MISSING"]
    if not isinstance(raw, list):
        assessment["policy_ref_status"] = "INCOMPLETE"
        return assessment, ["POLICY_REFERENCE_INVALID"]
    issues = set()
    has_unusable_policy = False
    for index, ref in enumerate(raw):
        key = _uuid(ref)
        if key is None:
            issues.add("POLICY_REFERENCE_INVALID")
        elif not policy_ids[key]:
            assessment["missing_policy_refs"].append(
                {"source_policy_id": ref, "source_position": index}
            )
            issues.add("POLICY_REFERENCE_NOT_FOUND")
        elif policy_ids[key] > 1:
            issues.add("POLICY_REFERENCE_AMBIGUOUS")
        elif key not in usable_policy_ids:
            has_unusable_policy = True
    assessment["policy_ref_status"] = "INCOMPLETE" if issues else "COMPLETE"
    if has_unusable_policy:
        assessment["policy_parse_status"] = "FAILED"
        issues.add("POLICY_REFERENCE_UNUSABLE")
    elif not issues:
        assessment["policy_parse_status"] = "PASSED"
    return assessment, sorted(issues)


def _records(snapshot, identities, *, policy_ids=None, usable_policy_ids=None):
    role = snapshot.entry["role"]
    for index, payload in enumerate(snapshot.records):
        obj = payload if isinstance(payload, dict) else {}
        source_id = obj.get(_IDS[role])
        key = _uuid(source_id)
        issues = []
        if not isinstance(payload, dict):
            issues.append("RECORD_NOT_OBJECT")
        if key is None:
            issues.append("SOURCE_ID_INVALID")
        elif identities[key] > 1:
            issues.append("SOURCE_ID_DUPLICATE")
        specifics = {}
        geometry = obj.get("geometry")
        if role in ("zones", "areas"):
            specifics["source_geometry_sha256"] = (
                digest(canonical(geometry)) if geometry is not None else None
            )
            specifics["geometry_evidence"] = "SOURCE_REPORTED"
        if role == "zones":
            policy_assessment, policy_issues = _zone_policies(
                obj, policy_ids, usable_policy_ids
            )
            issues.extend(_zone_geometry(geometry))
            crs = snapshot.entry.get("source_crs")
            if crs is not None and crs.upper() not in (
                "EPSG:4326",
                "OGC:CRS84",
                "CRS84",
                "WGS84",
            ):
                issues.append("ZONE_CRS_UNSUPPORTED")
            issues.extend(policy_issues)
            specifics.update(policy_assessment)
        elif role == "areas":
            issues.extend(_area_geometry(geometry))
        elif not _policy_supported(obj):
            issues.append("UNSUPPORTED_POLICY_FORM")
        yield {
            "role": role,
            "source_index": index,
            "source_id": source_id,
            "source_artifact_sha256": snapshot.entry["sha256"],
            "payload": payload,
            "status": "QUARANTINED" if issues else "PARSED",
            "issues": sorted(issues),
        } | specifics


def _stage_content(snapshots, batch_id, capture_digest, emit):
    policies = snapshots["policies"]
    policy_ids = _identities(policies)
    policy_records = list(_records(policies, policy_ids))
    usable_policy_ids = {
        _uuid(record["source_id"])
        for record in policy_records
        if record["status"] == "PARSED"
    }
    zone_policy_parse_counts = Counter()
    quarantine = []
    missing = []
    components = {}
    hashes = {}
    for role in ROLES:
        if role not in snapshots:
            continue
        snapshot = snapshots[role]
        ids = policy_ids if role == "policies" else _identities(snapshot)
        reasons = Counter()
        counts = Counter()

        def lines():
            records = (
                policy_records
                if role == "policies"
                else _records(
                    snapshot,
                    ids,
                    policy_ids=policy_ids,
                    usable_policy_ids=usable_policy_ids,
                )
            )
            for record in records:
                issues = record["issues"]
                counts[record["status"]] += 1
                if role == "zones":
                    zone_policy_parse_counts[record["policy_parse_status"]] += 1
                if issues:
                    reasons.update(issues)
                    quarantine.append(
                        {
                            key: record[key]
                            for key in (
                                "role",
                                "source_index",
                                "source_id",
                                "source_artifact_sha256",
                                "issues",
                            )
                        }
                    )
                for reference in record.get("missing_policy_refs", []):
                    missing.append(
                        {
                            "source_zone_id": record["source_id"],
                            "source_index": record["source_index"],
                        }
                        | reference
                    )
                yield canonical(record)

        name = f"{role}.ndjson"
        hashes[name] = emit(name, lines())
        components[role] = {
            "sha256": snapshot.entry["sha256"],
            "byte_size": snapshot.entry["byte_size"],
            "source_format": snapshot.entry["source_format"],
            "source_crs": snapshot.entry.get("source_crs"),
            "declared_source_as_of": snapshot.entry.get("source_as_of"),
            "source_metadata": snapshot.metadata,
            "source_timestamp": snapshot.timestamp,
            "record_count": len(snapshot.records),
            "duplicate_id_count": sum(count > 1 for count in ids.values()),
            "duplicate_id_record_count": reasons["SOURCE_ID_DUPLICATE"],
            "parsed_count": counts["PARSED"],
            "quarantined_count": counts["QUARANTINED"],
            "issue_counts": dict(reasons),
        }
    hashes["quarantine.ndjson"] = emit("quarantine.ndjson", map(canonical, quarantine))
    report = {
        "stage_schema_version": 2,
        "batch_id": str(batch_id),
        "capture_manifest_sha256": capture_digest,
        "public_eligible": False,
        "areas_not_included": "areas" not in snapshots,
        "components": components,
        "stage_files": hashes,
        "quarantined_count": len(quarantine),
        "missing_policy_ref_count": len(missing),
        "zones_with_missing_policy_refs": len({ref["source_index"] for ref in missing}),
        "missing_policy_refs": missing,
        "zone_policy_parse_status_counts": dict(zone_policy_parse_counts),
    }
    encoded = canonical(report)
    report_sha = emit("report.json", (encoded,))["sha256"]
    checksums = {name: info["sha256"] for name, info in hashes.items()} | {
        "report.json": report_sha
    }
    checksum_lines = tuple(
        f"{value}  {name}\n".encode("ascii")
        for name, value in sorted(checksums.items())
    )
    emit("SHA256SUMS", checksum_lines)
    return report_sha


def _emit_files(parent, snapshots, batch_id, capture_digest, existing):
    written = set()

    def emit(name, chunks):
        written.add(name)
        if existing:
            hasher = sha256()
            size = 0
            for chunk in chunks:
                hasher.update(chunk)
                size += len(chunk)
            expected = hasher.hexdigest(), size
            if (
                not files.present(parent, name)
                or files.fingerprint(parent, name) != expected
            ):
                raise CaptureError("STAGE_FILE_MISMATCH")
            file_sha, size = expected
        else:
            file_sha, size = files.write_file(parent, name, chunks)
        return {"sha256": file_sha, "byte_size": size}

    report_sha = _stage_content(snapshots, batch_id, capture_digest, emit)
    if set(os.listdir(parent)) != written:
        raise CaptureError("UNEXPECTED_STAGE_FILES")
    os.fsync(parent)
    return report_sha


def complete_stage(parent, snapshots, batch_id, capture_digest):
    """Recover the scratch directory and check a completed stage byte for byte."""
    name = str(batch_id)
    temporary = f".{name}.partial"
    files.remove_stage_temporary(parent, temporary)
    if files.present(parent, name):
        with files.directory(parent, (name,)) as target:
            return _emit_files(
                target, snapshots, batch_id, capture_digest, existing=True
            )

    os.mkdir(temporary, 0o700, dir_fd=parent)
    try:
        with files.directory(parent, (temporary,)) as target:
            report_sha = _emit_files(
                target, snapshots, batch_id, capture_digest, existing=False
            )
        files.promote(parent, temporary, name)
        return report_sha
    finally:
        files.remove_stage_temporary(parent, temporary)
