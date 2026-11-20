"""Classify source evidence and prepare links local to one batch."""

from collections import Counter
from dataclasses import dataclass, field
from itertools import batched

from data.cds_capture import stage
from data.cds_capture.manifest import CaptureError, canonical

_CRS = {"EPSG:4326", "OGC:CRS84", "CRS84", "WGS84"}
_EXCLUSIONS = {
    "RECORD_NOT_OBJECT",
    "SOURCE_ID_INVALID",
    "SOURCE_ID_DUPLICATE",
    "UNSUPPORTED_POLICY_FORM",
    "POLICY_REFERENCES_MISSING",
    "POLICY_REFERENCE_INVALID",
    "POLICY_REFERENCE_NOT_FOUND",
    "POLICY_REFERENCE_AMBIGUOUS",
    "POLICY_REFERENCE_UNUSABLE",
    "ZONE_GEOMETRY_NOT_LINESTRING",
    "ZONE_GEOMETRY_EMPTY",
    "ZONE_GEOMETRY_INVALID_COORDINATES",
    "ZONE_GEOMETRY_DEGENERATE",
    "ZONE_GEOMETRY_POSTGIS_INVALID",
    "ZONE_CRS_UNSUPPORTED",
}
_DISPOSITIONS = ("ACCEPTED", "REVIEW_REQUIRED", "EXCLUDED")
_INFORMATIONAL = {"ZONE_GEOMETRY_REPEATED_VERTEX"}


@dataclass
class Evidence:
    row: dict
    key: str | None
    reasons: set = field(default_factory=set)

    @property
    def payload(self):
        return self.row["payload"] if isinstance(self.row["payload"], dict) else {}

    @property
    def disposition(self):
        if self.reasons & _EXCLUSIONS:
            return "EXCLUDED"
        return "REVIEW_REQUIRED" if self.reasons - _INFORMATIONAL else "ACCEPTED"


def _source_records(rows):
    records = {}
    counts = {}
    for role, members in rows.items():
        group = [
            Evidence(row, stage._uuid(row["source_id"]), set(row["issues"]))
            for row in members
        ]
        ids = Counter(item.key for item in group if item.key is not None)
        for item in group:
            if not isinstance(item.row["payload"], dict):
                item.reasons.add("RECORD_NOT_OBJECT")
            if item.key is None:
                item.reasons.add("SOURCE_ID_INVALID")
            elif ids[item.key] > 1:
                item.reasons.add("SOURCE_ID_DUPLICATE")
        records[role] = group
        counts[role] = ids
    return records, counts


def _policy_qa(zones, policies, policy_ids, stage_report):
    for policy in policies:
        if not stage._policy_supported(policy.payload):
            policy.reasons.add("UNSUPPORTED_POLICY_FORM")
    usable = {item.key for item in policies if item.disposition == "ACCEPTED"}
    counts = Counter()
    missing_zone_ids = set()
    expected_missing = []
    parse_counts = Counter()
    for zone in zones:
        expected, issues = stage._zone_policies(zone.payload, policy_ids, usable)
        if any(zone.row.get(key) != value for key, value in expected.items()):
            raise CaptureError("STAGE_POLICY_QA_MISMATCH", "zones")
        zone.reasons.update(issues)
        parse_counts[expected["policy_parse_status"]] += 1
        raw = zone.payload.get("curb_policy_ids")
        if isinstance(raw, list):
            counts["declared_entries"] += len(raw)
        if expected["missing_policy_refs"]:
            counts["zone_rows_with_missing_references"] += 1
            if zone.key is not None:
                missing_zone_ids.add(zone.key)
            for missing in expected["missing_policy_refs"]:
                expected_missing.append(
                    {
                        "source_zone_id": zone.row["source_id"],
                        "source_index": zone.row["source_index"],
                        **missing,
                    }
                )
        for ref in raw if isinstance(raw, list) else ():
            key = stage._uuid(ref)
            if key is None:
                counts["invalid_ids"] += 1
            elif not policy_ids[key]:
                counts["missing_ids"] += 1
            elif policy_ids[key] != 1:
                counts["ambiguous_ids"] += 1
            else:
                counts["resolved_unique"] += 1
                if key not in usable:
                    counts["resolved_but_unusable"] += 1
    if (
        stage_report.get("missing_policy_refs") != expected_missing
        or stage_report.get("missing_policy_ref_count") != counts["missing_ids"]
        or stage_report.get("zones_with_missing_policy_refs")
        != counts["zone_rows_with_missing_references"]
        or stage_report.get("zone_policy_parse_status_counts") != dict(parse_counts)
    ):
        raise CaptureError("STAGE_POLICY_QA_MISMATCH", "zones")
    return {
        key: counts[key]
        for key in (
            "declared_entries",
            "invalid_ids",
            "missing_ids",
            "ambiguous_ids",
            "resolved_unique",
            "resolved_but_unusable",
            "zone_rows_with_missing_references",
        )
    } | {"distinct_zone_ids_with_missing_references": len(missing_zone_ids)}


def _side(value):
    if isinstance(value, str) and value.upper() in ("LEFT", "RIGHT"):
        return value.upper()
    return None


def _road_reference(item):
    value = item.payload.get("location_references")
    return value if isinstance(value, dict) else {}


def _zone_placement(item):
    side = _side(item.payload.get("street_side"))
    reference = _road_reference(item)
    ref_id = reference.get("ref_id")
    ref_side = _side(reference.get("side"))
    if side is None:
        item.reasons.add("STREET_SIDE_UNKNOWN")
    if side is not None and ref_side is not None and side != ref_side:
        item.reasons.add("SOURCE_STREET_SIDE_CONFLICT")
    if not (
        (
            isinstance(ref_id, str)
            and ref_id.strip()
            and ref_id.strip().upper() != "UNKNOWN"
        )
        or (type(ref_id) is int and ref_id > 0)
    ):
        item.reasons.add("ROAD_REFERENCE_MISSING")


def _polygon_rings(geometry):
    coordinates = geometry["coordinates"]
    polygons = [coordinates] if geometry["type"] == "Polygon" else coordinates
    return all(
        isinstance(polygon, list)
        and bool(polygon)
        and all(
            isinstance(ring, list)
            and len(ring) >= 4
            and all(map(stage._position, ring))
            and ring[0] == ring[-1]
            for ring in polygon
        )
        for polygon in polygons
    )


def _geometry_qa(connection, role, records, source_crs):
    if source_crs is None:
        crs_reason = "SOURCE_CRS_UNDECLARED"
    elif source_crs.upper() not in _CRS:
        crs_reason = (
            "ZONE_CRS_UNSUPPORTED" if role == "zones" else "AREA_CRS_UNSUPPORTED"
        )
    else:
        crs_reason = None

    geometries = []
    for item in records:
        geometry = item.payload.get("geometry")
        if crs_reason:
            item.reasons.add(crs_reason)
        if role == "zones":
            _zone_placement(item)
            structural = stage._zone_geometry(geometry)
        else:
            structural = stage._area_geometry(geometry)
            if not structural and not _polygon_rings(geometry):
                structural = ["AREA_GEOMETRY_INVALID_RINGS"]
        item.reasons.update(structural)
        if crs_reason in (None, "SOURCE_CRS_UNDECLARED") and not (
            set(structural) - {"ZONE_GEOMETRY_REPEATED_VERTEX"}
        ):
            geometries.append(
                (
                    item,
                    {"type": geometry["type"], "coordinates": geometry["coordinates"]},
                )
            )

    # GEOS topology is only a QA signal. Nothing here transforms source coordinates.
    for batch in batched(geometries, 256):
        encoded = canonical([geometry for _, geometry in batch]).decode("ascii")
        checks = connection.execute(
            """
            SELECT public.ST_IsValid(geom, 0), public.ST_IsSimple(geom)
            FROM (
                SELECT ordinal, public.ST_GeomFromGeoJSON(value) AS geom
                FROM json_array_elements(%s::json) WITH ORDINALITY AS fragments(value, ordinal)
            ) AS geometries
            ORDER BY ordinal
            """,
            (encoded,),
        )
        for (item, _), (valid, simple) in zip(batch, checks, strict=True):
            if valid is not True:
                code = (
                    "ZONE_GEOMETRY_POSTGIS_INVALID"
                    if role == "zones"
                    else "AREA_GEOMETRY_POSTGIS_INVALID"
                )
                item.reasons.add(code)
            elif role == "zones" and simple is not True:
                item.reasons.add("ZONE_GEOMETRY_NON_SIMPLE")


def _membership_direction(records, owner_ids, target_ids, *, field_name, issue_prefix):
    """Return unique, referentially sound directional pairs and source entry counts."""
    pairs = set()
    declared = invalid = missing = ambiguous = duplicate = malformed_lists = 0
    for item in records:
        raw = item.payload.get(field_name)
        if raw is None:
            if field_name == "curb_zone_ids":
                item.reasons.add("AREA_ZONE_MEMBERSHIP_UNDECLARED")
            continue
        if not isinstance(raw, list):
            item.reasons.add(f"{issue_prefix}_LIST_INVALID")
            malformed_lists += 1
            continue
        declared += len(raw)
        seen = set()
        for raw_id in raw:
            target = stage._uuid(raw_id)
            if target is None:
                item.reasons.add(f"{issue_prefix}_ID_INVALID")
                invalid += 1
                continue
            if target in seen:
                item.reasons.add(f"{issue_prefix}_DUPLICATE")
                duplicate += 1
            seen.add(target)
            if target_ids is None:
                continue
            if target_ids[target] == 0:
                item.reasons.add(f"{issue_prefix}_NOT_FOUND")
                missing += 1
            elif target_ids[target] > 1:
                item.reasons.add(f"{issue_prefix}_AMBIGUOUS")
                ambiguous += 1
            elif item.key is not None and owner_ids[item.key] == 1:
                pairs.add((item.key, target))
    return pairs, {
        "declared_entries": declared,
        "malformed_lists": malformed_lists,
        "invalid_id_entries": invalid,
        "missing_target_entries": missing if target_ids is not None else None,
        "ambiguous_target_entries": ambiguous if target_ids is not None else None,
        "duplicate_entries": duplicate,
        "valid_unique_pairs": len(pairs) if target_ids is not None else None,
    }


def _area_qa(records, ids):
    zones = records["zones"]
    has_areas = "areas" in records
    zones_to_areas, zone_metrics = _membership_direction(
        zones,
        ids["zones"],
        ids.get("areas"),
        field_name="curb_area_ids",
        issue_prefix="ZONE_AREA_REFERENCE",
    )
    if not has_areas:
        return set(), {
            "assessed": False,
            "from_zones": zone_metrics,
            "from_areas": None,
            "reciprocal_pairs": None,
            "zone_only_pairs": None,
            "area_only_pairs": None,
            "zones_without_area_or_road_reference": None,
        }

    areas = records["areas"]
    areas_to_zones, area_metrics = _membership_direction(
        areas,
        ids["areas"],
        ids["zones"],
        field_name="curb_zone_ids",
        issue_prefix="AREA_ZONE_REFERENCE",
    )
    reverse = {(zone, area) for area, zone in areas_to_zones}
    one_sided = zones_to_areas ^ reverse
    affected_zones = {zone for zone, _ in one_sided}
    affected_areas = {area for _, area in one_sided}
    mentioned_zones = {
        stage._uuid(raw_id)
        for area in areas
        if isinstance(members := area.payload.get("curb_zone_ids"), list)
        for raw_id in members
    }
    cohort = 0
    for zone in zones:
        if zone.key in affected_zones:
            zone.reasons.add("AREA_MEMBERSHIP_ONE_SIDED")
        if (
            zone.key is not None
            and ids["zones"][zone.key] == 1
            and zone.key not in mentioned_zones
            and zone.payload.get("curb_area_ids") in (None, [])
            and "ROAD_REFERENCE_MISSING" in zone.reasons
        ):
            zone.reasons.add("AREA_AND_ROAD_REFERENCE_MISSING")
            cohort += 1
    for area in areas:
        if area.key in affected_areas:
            area.reasons.add("AREA_MEMBERSHIP_ONE_SIDED")
    reciprocal = zones_to_areas & reverse
    return reciprocal, {
        "assessed": True,
        "from_zones": zone_metrics,
        "from_areas": area_metrics,
        "reciprocal_pairs": len(reciprocal),
        "zone_only_pairs": len(zones_to_areas - reverse),
        "area_only_pairs": len(reverse - zones_to_areas),
        "zones_without_area_or_road_reference": cohort,
    }


def assess(connection, stage_report, rows):
    records, ids = _source_records(rows)
    policies = _policy_qa(
        records["zones"], records["policies"], ids["policies"], stage_report
    )
    for role in ("zones", "areas"):
        if role in records:
            _geometry_qa(
                connection,
                role,
                records[role],
                stage_report["components"][role]["source_crs"],
            )
    reciprocal, area_metrics = _area_qa(records, ids)

    accepted = {
        role: {item.key: item for item in group if item.disposition == "ACCEPTED"}
        for role, group in records.items()
    }
    policy_links = []
    for key, zone in accepted["zones"].items():
        for position, ref in enumerate(zone.payload["curb_policy_ids"]):
            policy_id = stage._uuid(ref)
            if policy_id not in accepted["policies"]:
                raise CaptureError("CANDIDATE_POLICY_LINEAGE_MISMATCH")
            policy_links.append(
                {"zone_id": key, "policy_id": policy_id, "source_position": position}
            )

    area_links = [
        {"zone_id": zone_id, "area_id": area_id}
        for zone_id, area_id in sorted(reciprocal)
        if zone_id in accepted["zones"] and area_id in accepted["areas"]
    ]
    policies["candidate_links"] = len(policy_links)
    if area_metrics["assessed"]:
        area_metrics["candidate_links"] = len(area_links)
        area_metrics["omitted_reciprocal_pairs"] = len(reciprocal) - len(area_links)
    else:
        area_metrics["candidate_links"] = None
        area_metrics["omitted_reciprocal_pairs"] = None

    summary = {}
    for role, group in records.items():
        dispositions = Counter(item.disposition for item in group)
        summary[role] = {
            "input_rows": len(group),
            "dispositions": {state: dispositions[state] for state in _DISPOSITIONS},
            "reason_row_counts": dict(
                Counter(reason for item in group for reason in item.reasons)
            ),
            "exclusion_reason_row_counts": dict(
                Counter(
                    reason for item in group for reason in item.reasons & _EXCLUSIONS
                )
            ),
        }
    candidate = {
        "accepted_records": {
            role: [
                {"source_id": key, "source_index": item.row["source_index"]}
                for key, item in group.items()
            ]
            for role, group in accepted.items()
        },
        "zone_policy_links": policy_links,
        "area_zone_links": area_links,
    }
    return (
        records,
        candidate,
        {
            "roles": summary,
            "policy_references": policies,
            "area_membership": area_metrics,
        },
    )
