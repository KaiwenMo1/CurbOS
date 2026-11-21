"""Read the catalog and compare the verified projection with the stored boundary."""

import os
import re
from hashlib import file_digest
from uuid import NAMESPACE_URL, UUID, uuid5

from data.cds_capture.manifest import CaptureError, _safe_uri, canonical, digest
from data.cds_validate.integrity import _regular


def verify_artifacts(root, lineage):
    for role, artifact in lineage["artifacts"].items():
        sha, size = artifact["sha256"], artifact["byte_size"]
        try:
            with _regular(root, sha, size) as handle:
                if (
                    os.fstat(handle.fileno()).st_size != size
                    or file_digest(handle, "sha256").hexdigest() != sha
                ):
                    raise CaptureError("RAW_ARTIFACT_DIGEST_MISMATCH", role)
        except CaptureError as error:
            if error.code == "RAW_ARTIFACT_DIGEST_MISMATCH":
                raise
            raise CaptureError("RAW_ARTIFACT_UNAVAILABLE_OR_UNSAFE", role) from None


def source_registry(connection, lineage):
    row = connection.execute(
        """
        SELECT publisher_key, dataset_key, source_profile, catalog_uri, rights_status,
               nullif(btrim(rights_reference), '') IS NOT NULL
        FROM sources.source_dataset WHERE dataset_id = %s
        """,
        (UUID(lineage["dataset_id"]),),
    ).fetchone()
    if row is None:
        raise CaptureError("SOURCE_DATASET_MISSING")
    publisher, dataset, profile, catalog, rights, rights_ref_present = row
    if any(
        not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", key)
        for key in (publisher, dataset, profile)
    ) or not _safe_uri(catalog):
        raise CaptureError("SOURCE_IDENTITY_METADATA_INVALID")
    origins = {}
    for role, retrieved, as_of, uri in connection.execute(
        """
        SELECT j.component_role, a.retrieved_at, a.source_as_of, a.metadata->>'original_source_uri'
        FROM sources.import_artifact j JOIN sources.raw_artifact a USING (artifact_id)
        WHERE j.batch_id = %s ORDER BY j.component_role
        """,
        (UUID(lineage["batch_id"]),),
    ):
        if not isinstance(uri, str) or not _safe_uri(uri):
            raise CaptureError("SOURCE_ORIGIN_METADATA_INVALID", role)
        origins[role] = {
            "evidence_ref": f"artifact:{lineage['artifacts'][role]['artifact_id']}",
            "distribution_uri_sha256": digest(uri.encode("utf-8")),
            "registered_acquired_at": retrieved.isoformat(),
            "source_as_of": as_of.isoformat() if as_of is not None else None,
        }
    return {
        "publisher_key": publisher,
        "dataset_key": dataset,
        "source_profile": profile,
        "source_class": "SYNTHETIC_DECLARED"
        if profile == "synthetic-cds-json" and publisher == "synthetic-test"
        else "REAL_OR_UNCLASSIFIED",
        "catalog_uri_sha256": digest(catalog.encode("utf-8")),
        "registered_rights_status": rights,
        "registry_rights_reference_present": rights_ref_present,
        "component_origins": origins,
    }


def coverage(connection, scope, zones):
    status, reviewed, sha = connection.execute(
        """
        SELECT review_status, reviewed_at IS NOT NULL,
               encode(sha256(public.ST_AsEWKB(reviewed_geom, 'XDR')), 'hex')
        FROM sources.publication_scope WHERE scope_key = %s
        """,
        (scope,),
    ).fetchone()
    result = {
        "scope_review_status": status,
        "review_recorded": reviewed,
        "boundary_sha256": sha,
        "comparison_status": "NOT_ASSESSED",
        "denominator_projected_zone_lines": len(zones),
        "fully_covered": None,
        "intersecting_not_covered": None,
        "disjoint": None,
        "not_fully_covered_zone_ids": None,
        "area_membership_is_coverage": False,
    }
    if sha is None:
        return result
    lines = [{"id": zone["id"], "geometry": zone["geometry"]} for zone in zones]
    fully = intersecting = disjoint = 0
    excluded = []
    for source_id, covered, intersects in connection.execute(
        """
        WITH projected AS MATERIALIZED (
            SELECT id, publication.source_geometry(geometry, 'zones') AS geom
            FROM jsonb_to_recordset(%s::jsonb) AS z(id text, geometry jsonb)
        )
        SELECT id, public.ST_CoveredBy(geom, reviewed_geom), public.ST_Intersects(geom, reviewed_geom)
        FROM projected CROSS JOIN sources.publication_scope WHERE scope_key = %s
        ORDER BY id COLLATE "C"
        """,
        (canonical(lines).decode("ascii"), scope),
    ):
        if covered is None or intersects is None:
            raise CaptureError("COVERAGE_PROJECTION_MISMATCH")
        if covered:
            fully += 1
        else:
            excluded.append(source_id)
            if intersects:
                intersecting += 1
            else:
                disjoint += 1
    if fully + len(excluded) != len(zones):
        raise CaptureError("COVERAGE_PROJECTION_MISMATCH")
    return result | {
        "comparison_status": "BOUNDARY_GEOMETRY_ONLY",
        "fully_covered": fully,
        "intersecting_not_covered": intersecting,
        "disjoint": disjoint,
        "not_fully_covered_zone_ids": excluded,
    }


def registration(connection, lineage, candidate_id, report_sha, plan):
    plan_sha = connection.execute(
        "SELECT encode(sha256(convert_to((%s::jsonb)::text, 'UTF8')), 'hex')",
        (canonical(plan).decode("ascii"),),
    ).fetchone()[0]
    release_id = uuid5(NAMESPACE_URL, f"curbos:cds-release:v1:{candidate_id}")
    rows = connection.execute(
        """
        SELECT r.release_id, r.batch_id, r.scope_key, r.status, r.validation_report_sha256,
               e.candidate_id, e.report_sha256, e.plan_sha256, e.lineage, e.review_required,
               (v.release_id IS NOT NULL), (a.release_id IS NOT NULL),
               coalesce(p.release_id = r.release_id, false)
        FROM sources.dataset_release r
        LEFT JOIN publication.release_evidence e USING (release_id)
        LEFT JOIN publication.release_verification v USING (release_id)
        LEFT JOIN publication.release_approval a USING (release_id)
        LEFT JOIN sources.active_release p ON p.scope_key = r.scope_key
        WHERE r.release_id = %s OR e.candidate_id = %s
        """,
        (release_id, UUID(candidate_id)),
    ).fetchall()
    if not rows:
        return {"status": "NOT_REGISTERED", "projection_plan_sha256": plan_sha}
    if len(rows) != 1:
        raise CaptureError("RELEASE_REGISTRATION_MISMATCH")
    row = rows[0]
    if row[:3] != (release_id, UUID(lineage["batch_id"]), lineage["scope_key"]) or row[
        4:10
    ] != (
        report_sha,
        UUID(candidate_id),
        report_sha,
        plan_sha,
        lineage,
        plan["review_required"],
    ):
        raise CaptureError("RELEASE_REGISTRATION_MISMATCH")
    return {
        "status": row[3],
        "release_id": str(release_id),
        "projection_plan_sha256": plan_sha,
        "verified_receipt_present": row[10],
        "approval_receipt_present": row[11],
        "is_active_pointer_target": row[12],
    }
