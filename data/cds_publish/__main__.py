"""Register a verified private CDS candidate using the registrar role."""

import argparse
import os
import re
import sys
from itertools import batched
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from data.cds_capture import database, files
from data.cds_capture.manifest import CaptureError, canonical
from data.cds_validate.__main__ import _package_files, _path_pair, prepare


def _unrepresentable(connection, role, geometries):
    omitted = set()
    for batch in batched(geometries.items(), 256):
        data = canonical([geometry for _, geometry in batch]).decode("ascii")
        checked = connection.execute(
            """
            SELECT publication.source_geometry(value, %s) IS NOT NULL
            FROM jsonb_array_elements(%s::jsonb) WITH ORDINALITY AS g(value, position)
            ORDER BY position
            """,
            (role, data),
        )
        for (source_id, _), (representable,) in zip(batch, checked, strict=True):
            if not representable:
                omitted.add(source_id)
    return omitted


def _text(value):
    return value if isinstance(value, str) else None


def _projection_plan(connection, records, candidate, summary):
    plan = {
        "zones": [],
        "policies": [],
        "areas": [],
        "review_required": [],
        "qa": [],
    }
    omitted = {}
    included = {}
    for role, group in records.items():
        accepted = {item.key: item for item in group if item.disposition == "ACCEPTED"}
        omitted[role] = (
            _unrepresentable(
                connection,
                role,
                {key: item.payload["geometry"] for key, item in accepted.items()},
            )
            if role in ("zones", "areas")
            else set()
        )
        included[role] = accepted.keys() - omitted[role]
        for item in group:
            locator = f"{role}:{item.row['source_index']}"
            is_omitted = item.key in omitted[role]
            if item.disposition == "REVIEW_REQUIRED":
                plan["review_required"].append(locator)
            disposition = {
                "ACCEPTED": "RETAINED",
                "REVIEW_REQUIRED": "WITHHELD_PENDING_REVIEW",
                "EXCLUDED": "EXCLUDED",
            }[item.disposition]
            if is_omitted:
                disposition = "EXCLUDED"
                plan["qa"].append(
                    {
                        "role": role,
                        "source_id": item.key,
                        "locator": locator,
                        "severity": "ERROR",
                        "disposition": disposition,
                        "reason": "ZONE_GEOMETRY_UNREPRESENTABLE"
                        if role == "zones"
                        else "AREA_GEOMETRY_UNREPRESENTABLE",
                    }
                )
            for reason in sorted(item.reasons):
                plan["qa"].append(
                    {
                        "role": role,
                        "source_id": item.key,
                        "locator": locator,
                        "severity": "INFO" if disposition == "RETAINED" else "WARNING",
                        "disposition": disposition,
                        "reason": reason,
                    }
                )
            if item.disposition != "ACCEPTED" or is_omitted:
                continue
            payload = item.payload
            if role == "zones":
                reference = payload["location_references"]["ref_id"]
                spaces = payload.get("num_spaces")
                spaces = (
                    spaces
                    if type(spaces) is int and 0 <= spaces <= 2147483647
                    else None
                )
                plan["zones"].append(
                    {
                        "id": item.key,
                        "geometry": payload["geometry"],
                        "geometry_sha256": item.row["source_geometry_sha256"],
                        "street_side": payload["street_side"].upper(),
                        "road_reference": str(reference),
                        "source_num_spaces": spaces,
                    }
                )
            elif role == "policies":
                plan["policies"].append({"id": item.key, "payload": payload})
            else:
                plan["areas"].append(
                    {
                        "id": item.key,
                        "geometry": payload["geometry"],
                        "name": _text(payload.get("name")),
                        "description": _text(payload.get("description")),
                    }
                )
    plan["zone_policy_links"] = [
        link
        for link in candidate["zone_policy_links"]
        if link["zone_id"] in included["zones"]
        and link["policy_id"] in included["policies"]
    ]
    plan["area_zone_links"] = [
        link
        for link in candidate["area_zone_links"]
        if link["zone_id"] in included["zones"]
        and link["area_id"] in included.get("areas", ())
    ]
    plan["summary"] = {
        "candidate_qa": summary,
        "projected": {role: len(plan[role]) for role in ("zones", "policies", "areas")},
        "projection_geometry_exclusions": {
            role: len(keys) for role, keys in omitted.items()
        },
        "omitted_zone_policy_links": len(candidate["zone_policy_links"])
        - len(plan["zone_policy_links"]),
        "omitted_area_zone_links": len(candidate["area_zone_links"])
        - len(plan["area_zone_links"]),
    }
    return plan


def register(
    batch_id,
    scope_key,
    stage_dir,
    candidate_dir,
    expected_report_sha,
    *,
    db_socket_dir=None,
):
    if not re.fullmatch(r"[0-9a-f]{64}", expected_report_sha):
        raise CaptureError("INVALID_CANDIDATE_REPORT_DIGEST")
    stage_dir, candidate_dir = _path_pair(stage_dir, candidate_dir)
    with (
        files.root(stage_dir, private=True) as staged,
        files.root(candidate_dir, private=True) as package,
    ):
        if os.path.samestat(os.fstat(staged), os.fstat(package)):
            raise CaptureError("OVERLAPPING_VALIDATION_PATHS")
        with database.transaction(db_socket_dir) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            lineage, candidate_id, records, candidate, summary = prepare(
                connection, batch_id, scope_key, staged
            )
            if candidate_dir.name != candidate_id:
                raise CaptureError("CANDIDATE_IDENTITY_MISMATCH")
            actual = _package_files(
                package, lineage, candidate_id, records, candidate, summary, True
            )
            if actual != expected_report_sha:
                raise CaptureError("CANDIDATE_REPORT_DIGEST_MISMATCH")

            plan = _projection_plan(connection, records, candidate, summary)
            release_id = uuid5(NAMESPACE_URL, f"curbos:cds-release:v1:{candidate_id}")
            result = connection.execute(
                "SELECT publication.register_candidate(%s, %s, %s, %s::jsonb, %s::jsonb)",
                (
                    release_id,
                    UUID(candidate_id),
                    actual,
                    canonical(lineage).decode("ascii"),
                    canonical(plan).decode("ascii"),
                ),
            ).fetchone()[0]
    return result | {
        "candidate_id": candidate_id,
        "review_required": plan["review_required"],
        "summary": plan["summary"],
    }


class _Arguments(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, '{"code":"INVALID_ARGUMENTS","state":"FAILED"}\n')


def main():
    parser = _Arguments(description=__doc__)
    parser.add_argument("--batch-id", required=True, type=UUID)
    parser.add_argument("--scope-key", required=True)
    parser.add_argument("--stage-dir", required=True, type=Path)
    parser.add_argument("--candidate-dir", required=True, type=Path)
    parser.add_argument("--expected-report-sha", required=True)
    parser.add_argument("--db-socket-dir", type=Path)
    try:
        result = register(**vars(parser.parse_args()))
    except (CaptureError, OSError) as error:
        code = (
            error.code
            if isinstance(error, CaptureError)
            else "PUBLICATION_FILESYSTEM_FAILURE"
        )
        sys.stderr.write(canonical({"state": "FAILED", "code": code}).decode("ascii"))
        return 1
    sys.stdout.write(canonical(result).decode("ascii"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
