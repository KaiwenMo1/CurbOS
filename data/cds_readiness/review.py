"""Readiness policy and QA summaries for an already verified candidate."""

import re
from collections import Counter

from data.cds_capture.manifest import CaptureError
from data.cds_capture.stage import _uuid

VERSION = 1
SHA256 = re.compile(r"[0-9a-f]{64}")
REVIEW_REFERENCE = re.compile(r"evidence:[A-Za-z0-9][A-Za-z0-9_.-]{0,119}")
RIGHTS = (
    "publisher_identity",
    "distribution_origin",
    "acquisition_date",
    "published_terms",
    "private_storage",
    "transformation",
    "geometry_redistribution",
    "attribution",
    "commercial_and_public_use_restrictions",
    "downstream_map_display",
    "revocation_and_updates",
)
EVIDENCE = ("source_qa_decisions", "independent_coverage", "independent_placement")
PLACEMENT_CLAIMS = ("SOURCE_REPORTED_ONLY", "INDEPENDENTLY_VERIFIED")
COMPARABLE_METRICS = (
    "zone_source_rows",
    "distinct_valid_zone_ids",
    "policy_source_rows",
    "missing_policy_reference_entries",
    "zone_rows_with_missing_policy_references",
    "zone_rows_with_repeated_vertices",
    "zone_rows_without_area_or_road_reference",
    "zone_rows_missing_street_side",
    "area_source_rows",
    "area_to_zone_declared_entries",
    "zone_to_area_declared_entries",
    "reciprocal_area_zone_pairs",
)
GEOMETRY_TYPES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
    "GeometryCollection",
}
UNKNOWN = {"state": "UNKNOWN", "evidence_ref": None}


def _item(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"state", "evidence_ref"}
        or value["state"] not in ("APPROVED", "BLOCKED", "UNKNOWN")
    ):
        raise CaptureError("INVALID_EVIDENCE_ITEM")
    ref = value["evidence_ref"]
    if value["state"] in ("APPROVED", "BLOCKED"):
        if not isinstance(ref, str) or not REVIEW_REFERENCE.fullmatch(ref):
            raise CaptureError("INVALID_EVIDENCE_REFERENCE")
    elif ref is not None:
        raise CaptureError("INVALID_EVIDENCE_REFERENCE")
    return value


def checklist(review, binding, boundary_sha, locators):
    items = {name: UNKNOWN.copy() for name in (*RIGHTS, *EVIDENCE)}
    if review is None:
        return items, "SOURCE_REPORTED_ONLY", {}
    allowed = {
        "schema_version",
        "binding",
        "items",
        "placement_claim",
        "reviewed_boundary_sha256",
        "withheld_records",
    }
    if (
        not isinstance(review, dict)
        or set(review) - allowed
        or type(review.get("schema_version")) is not int
        or review["schema_version"] != VERSION
        or not isinstance(review.get("items"), dict)
        or set(review["items"]) - items.keys()
    ):
        raise CaptureError("INVALID_EVIDENCE_CHECKLIST")
    if review.get("binding") != binding:
        raise CaptureError("EVIDENCE_BINDING_MISMATCH")
    claim = review.get("placement_claim", "SOURCE_REPORTED_ONLY")
    if claim not in PLACEMENT_CLAIMS:
        raise CaptureError("INVALID_PLACEMENT_CLAIM")
    items.update({key: _item(value) for key, value in review["items"].items()})

    reviewed = review.get("reviewed_boundary_sha256")
    if reviewed is not None and (
        not isinstance(reviewed, str) or not SHA256.fullmatch(reviewed)
    ):
        raise CaptureError("INVALID_EVIDENCE_BOUNDARY_DIGEST")
    if (
        reviewed is not None or items["independent_coverage"]["state"] == "APPROVED"
    ) and (reviewed is None or reviewed != boundary_sha):
        raise CaptureError("EVIDENCE_BOUNDARY_MISMATCH")

    withheld = review.get("withheld_records", {})
    if not isinstance(withheld, dict) or set(withheld) - set(locators):
        raise CaptureError("INVALID_REVIEW_DISPOSITION")
    for ref in withheld.values():
        if not isinstance(ref, str) or not REVIEW_REFERENCE.fullmatch(ref):
            raise CaptureError("INVALID_EVIDENCE_REFERENCE")
    return items, claim, withheld


def _locator(role, record, lineage):
    return {
        "source_id": record.key,
        "source_index": record.row["source_index"],
        "artifact_id": lineage["artifacts"][role]["artifact_id"],
        "evidence_ref": f"stage:{role}:{record.row['source_index']}",
    }


def _policy_usage(policies):
    counts = Counter()
    for item in policies:
        rules = item.payload.get("rules")
        for entry in rules if isinstance(rules, list) else ():
            activity = entry.get("activity") if isinstance(entry, dict) else None
            if isinstance(activity, str) and re.fullmatch(
                r"[A-Za-z0-9_-]{1,64}", activity
            ):
                counts[activity] += 1
            else:
                counts[None] += 1
    unknown = counts.pop(None, 0)
    return {
        "denominator_rule_entries": sum(counts.values()) + unknown,
        "source_activity_entry_counts": dict(counts),
        "unclassified_entries": unknown,
        "legal_semantics": "UNKNOWN",
    }


def _unsupported_policy_shape(payload):
    rules = payload.get("rules")
    if not isinstance(rules, list):
        return {"rules_value_type": type(rules).__name__, "list_entries": None}
    entries = []
    for rule in rules:
        shape = {"type": type(rule).__name__}
        if isinstance(rule, dict):
            classes = rule.get("user_classes")
            shape |= {
                "activity_type": type(rule.get("activity")).__name__,
                "user_classes_type": type(classes).__name__
                if "user_classes" in rule
                else "ABSENT",
                "user_class_entry_types": dict(
                    Counter(type(item).__name__ for item in classes)
                )
                if isinstance(classes, list)
                else None,
            }
        entries.append(shape)
    return {"rules_value_type": "list", "list_entries": entries}


def qa_summary(records, summary, plan, lineage):
    policy_ids = Counter(p.key for p in records["policies"] if p.key is not None)
    unusable = {
        p.key
        for p in records["policies"]
        if policy_ids[p.key] == 1 and p.disposition != "ACCEPTED"
    }
    affected = {}
    for role, group in records.items():
        affected[role] = []
        for item in group:
            if not item.reasons:
                continue
            finding = _locator(role, item, lineage) | {
                "disposition": item.disposition,
                "reason_codes": sorted(item.reasons),
            }
            if role == "zones":
                finding["missing_policy_references"] = [
                    {
                        "source_policy_id": _uuid(ref["source_policy_id"]),
                        "source_position": ref["source_position"],
                    }
                    for ref in item.row["missing_policy_refs"]
                ]
                if "POLICY_REFERENCE_UNUSABLE" in item.reasons:
                    finding["unusable_policy_references"] = [
                        {"source_policy_id": policy_id, "source_position": position}
                        for position, ref in enumerate(item.payload["curb_policy_ids"])
                        if (policy_id := _uuid(ref)) in unusable
                    ]
            if role == "policies" and "UNSUPPORTED_POLICY_FORM" in item.reasons:
                finding["unsupported_policy_shape"] = _unsupported_policy_shape(
                    item.payload
                )
            affected[role].append(finding)

    areas = []
    for item in records.get("areas", []):
        geometry = item.payload.get("geometry")
        kind = geometry.get("type") if isinstance(geometry, dict) else None
        empty = isinstance(geometry, dict) and geometry.get("coordinates") == []
        reasons = item.reasons
        failed = any(reason.startswith("AREA_GEOMETRY_") for reason in reasons)
        assessed = "AREA_CRS_UNSUPPORTED" not in reasons
        areas.append(
            _locator("areas", item, lineage)
            | {
                "geometry_type": kind
                if isinstance(kind, str) and kind in GEOMETRY_TYPES
                else "UNKNOWN",
                "empty_geometry": empty,
                "geometry_status": "FAILED"
                if failed
                else "PASSED"
                if assessed
                else "NOT_ASSESSED",
            }
        )

    policy_metrics = summary["policy_references"]
    area_metrics = summary["area_membership"]
    metrics = {
        "zone_source_rows": len(records["zones"]),
        "distinct_valid_zone_ids": len({z.key for z in records["zones"] if z.key}),
        "policy_source_rows": len(records["policies"]),
        "missing_policy_reference_entries": policy_metrics["missing_ids"],
        "zone_rows_with_missing_policy_references": policy_metrics[
            "zone_rows_with_missing_references"
        ],
        "zone_rows_with_repeated_vertices": sum(
            "ZONE_GEOMETRY_REPEATED_VERTEX" in row.reasons for row in records["zones"]
        ),
        "zone_rows_without_area_or_road_reference": area_metrics[
            "zones_without_area_or_road_reference"
        ],
        "zone_rows_missing_street_side": sum(
            row.payload.get("street_side") is None for row in records["zones"]
        ),
        "area_source_rows": len(areas) if area_metrics["assessed"] else None,
        "area_to_zone_declared_entries": (
            area_metrics["from_areas"]["declared_entries"]
            if area_metrics["assessed"]
            else None
        ),
        "zone_to_area_declared_entries": area_metrics["from_zones"]["declared_entries"],
        "reciprocal_area_zone_pairs": area_metrics["reciprocal_pairs"],
    }
    structural_fails = sum(
        "UNSUPPORTED_POLICY_FORM" in p.reasons for p in records["policies"]
    )
    geometry_reasons = (
        "ZONE_GEOMETRY_UNREPRESENTABLE",
        "AREA_GEOMETRY_UNREPRESENTABLE",
    )
    projection = plan["summary"]
    return {
        "roles": summary["roles"],
        "affected_records": affected,
        "policy_references": policy_metrics
        | {
            "zone_rows_with_unusable_references": sum(
                "POLICY_REFERENCE_UNUSABLE" in z.reasons for z in records["zones"]
            ),
            "zone_parse_status_counts": dict(
                Counter(z.row["policy_parse_status"] for z in records["zones"])
            ),
        },
        "policy_structure": {
            "denominator_policy_rows": len(records["policies"]),
            "passed": len(records["policies"]) - structural_fails,
            "failed": structural_fails,
            "usable_distinct_ids": sum(
                p.disposition == "ACCEPTED" for p in records["policies"]
            ),
        },
        "policy_usage": _policy_usage(records["policies"]),
        "area_membership": area_metrics,
        "area_geometry": {
            "status": "ASSESSED" if area_metrics["assessed"] else "NOT_ASSESSED",
            "denominator_area_rows": metrics["area_source_rows"],
            "status_counts": dict(Counter(area["geometry_status"] for area in areas)),
            "records": areas,
        },
        "projection": {
            **{
                key: value for key, value in projection.items() if key != "candidate_qa"
            },
            "geometry_exclusions": [
                {
                    **issue,
                    "artifact_id": lineage["artifacts"][issue["role"]]["artifact_id"],
                }
                for issue in plan["qa"]
                if issue["reason"] in geometry_reasons
            ],
            "review_required_locators": plan["review_required"],
        },
        "comparable_metrics": metrics,
    }


def compare_history(baseline, basis, qa):
    if baseline is None:
        return {"status": "NOT_ASSESSED", "reason": "NO_VERSIONED_AUDIT_BASELINE"}
    if (
        not isinstance(baseline, dict)
        or set(baseline)
        != {"schema_version", "basis", "evidence_ref", "metrics", "areas"}
        or type(baseline["schema_version"]) is not int
        or baseline["schema_version"] != VERSION
        or not isinstance(baseline["basis"], dict)
        or not isinstance(baseline["metrics"], dict)
        or not isinstance(baseline["areas"], dict)
        or set(baseline["metrics"]) - set(COMPARABLE_METRICS)
        or not (baseline["metrics"] or baseline["areas"])
        or any(
            type(count) is not int or count < 0
            for count in baseline["metrics"].values()
        )
    ):
        raise CaptureError("INVALID_AUDIT_BASELINE")
    ref = baseline["evidence_ref"]
    if not isinstance(ref, str) or not REVIEW_REFERENCE.fullmatch(ref):
        raise CaptureError("INVALID_EVIDENCE_REFERENCE")
    for identifier, area in baseline["areas"].items():
        if (
            identifier != _uuid(identifier)
            or not isinstance(area, dict)
            or set(area) != {"geometry_type", "empty_geometry"}
            or not isinstance(area["geometry_type"], str)
            or area["geometry_type"] not in GEOMETRY_TYPES
            or type(area["empty_geometry"]) is not bool
        ):
            raise CaptureError("INVALID_AUDIT_BASELINE")

    if baseline["basis"] != basis:
        return {
            "status": "NOT_ASSESSED",
            "reason": "AUDIT_SNAPSHOT_OR_VERSION_MISMATCH",
            "evidence_ref": ref,
        }

    def difference(expected, observed):
        return {
            "expected": expected,
            "observed": observed,
            "status": "NOT_ASSESSED"
            if observed is None
            else "MATCH"
            if expected == observed
            else "DIFFERENT",
        }

    area_ids = Counter(row["source_id"] for row in qa["area_geometry"]["records"])
    areas = {
        row["source_id"]: {key: row[key] for key in ("geometry_type", "empty_geometry")}
        for row in qa["area_geometry"]["records"]
        if row["source_id"] is not None and area_ids[row["source_id"]] == 1
    }
    return {
        "status": "COMPARED",
        "evidence_ref": ref,
        "metrics": {
            name: difference(value, qa["comparable_metrics"][name])
            for name, value in baseline["metrics"].items()
        },
        "areas": {
            name: difference(value, areas.get(name))
            for name, value in baseline["areas"].items()
        },
        "difference_review": "CHECK_SNAPSHOT_VERSIONS_QA_ALGORITHM_AND_DENOMINATORS",
    }


def _block(code, evidence_ref):
    return {"code": code, "evidence_ref": evidence_ref}


def outcomes(items, source, coverage, claim, plan, withheld):
    evidence = []
    required = {
        "source_qa_decisions": "SOURCE_QA_DECISIONS_MISSING_OR_BLOCKED",
        "independent_coverage": "INDEPENDENT_COVERAGE_REVIEW_MISSING_OR_BLOCKED",
    }
    if claim == "INDEPENDENTLY_VERIFIED":
        required["independent_placement"] = (
            "INDEPENDENT_PLACEMENT_REVIEW_MISSING_OR_BLOCKED"
        )
    for key, code in required.items():
        item = items[key]
        if item["state"] != "APPROVED":
            evidence.append(_block(code, item["evidence_ref"] or f"checklist:{key}"))
    if (
        coverage["scope_review_status"] != "APPROVED"
        or not coverage["review_recorded"]
        or coverage["boundary_sha256"] is None
    ):
        evidence.append(
            _block("APPROVED_SCOPE_BOUNDARY_UNAVAILABLE", "coverage:scope_registry")
        )
    if coverage["not_fully_covered_zone_ids"]:
        evidence.append(
            _block(
                "PROJECTED_ZONES_OUTSIDE_REVIEWED_BOUNDARY",
                "coverage:not_fully_covered_zone_ids",
            )
        )
    if set(plan["review_required"]) - withheld.keys():
        evidence.append(
            _block(
                "REVIEW_REQUIRED_RECORDS_LACK_DOCUMENTED_DISPOSITION",
                "qa:projection.review_required_locators",
            )
        )
    if not plan["zones"]:
        evidence.append(
            _block("NO_REPRESENTABLE_CANDIDATE_ZONES", "qa:projection.projected.zones")
        )
    if claim == "INDEPENDENTLY_VERIFIED":
        evidence.append(
            _block("PROJECTION_REMAINS_SOURCE_REPORTED", "placement:projected_zones")
        )

    rights = []
    if (
        source["registered_rights_status"] != "APPROVED"
        or not source["registry_rights_reference_present"]
    ):
        state = source["registered_rights_status"]
        rights.append(
            _block(
                "SOURCE_RIGHTS_BLOCKED"
                if state in ("DENIED", "WITHDRAWN")
                else "SOURCE_RIGHTS_UNKNOWN",
                "source:registered_rights_status",
            )
        )
    for name in RIGHTS:
        item = items[name]
        if item["state"] != "APPROVED":
            rights.append(
                _block(
                    f"RIGHTS_{name.upper()}_{item['state']}",
                    item["evidence_ref"] or f"checklist:{name}",
                )
            )

    publication = (
        evidence
        + rights
        + [
            _block(
                "PRODUCTION_PUBLICATION_PROCESS_UNAUTHORIZED",
                "policy:production_publication_process",
            ),
            _block(
                "REAL_WORLD_PUBLICATION_AUTHORIZATION_MISSING",
                "policy:real_world_publication_authorization",
            ),
            _block(
                "SYNTHETIC_ONLY_ACTIVATION_AND_NO_REAL_SERVING",
                "policy:real_data_serving",
            ),
            _block("REAL_WITHDRAWAL_NOT_REHEARSED", "policy:real_withdrawal"),
        ]
    )
    return {
        "TECHNICAL_READINESS": {
            "status": "PASS",
            "reasons": [],
            "evidence_refs": [
                "lineage:retained_artifacts",
                "lineage:stage_report",
                "lineage:candidate_report",
                "qa:projection",
            ],
        },
        "EVIDENCE_READINESS": {
            "status": "BLOCKED" if evidence else "PASS",
            "reasons": evidence,
            "evidence_refs": [
                "qa:affected_records",
                "coverage:scope_registry",
                "placement:projected_zones",
            ],
        },
        "PUBLICATION_READINESS": {
            "status": "BLOCKED",
            "reasons": publication,
            "evidence_refs": [
                "source:registered_rights_status",
                "policy:real_data_serving",
            ],
        },
    }
