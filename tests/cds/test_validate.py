"""Synthetic PR-03 stage validation against the disposable provenance database."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from psycopg import sql

from data.cds_capture import database
from data.cds_capture.__main__ import run as capture
from data.cds_capture.manifest import CaptureError, canonical, digest, parse_json
from data.cds_validate.__main__ import run as validate
from fixtures import (
    Bundle,
    envelope,
    key,
    offline_command_prefix,
    policy,
    prepare_disposable_database,
    zone,
)

_SCOPE = "synthetic-research"
_POLYGON = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]],
}


def curb(number=1, *, refs=None, geometry=None, areas=()):
    return zone(number, policies=refs, geometry=geometry) | {
        "street_side": "LEFT",
        "location_references": {"ref_id": "synthetic-road", "side": "LEFT"},
        "curb_area_ids": list(areas),
    }


def area(number, members, geometry=_POLYGON):
    return {"curb_area_id": key(number), "curb_zone_ids": members, "geometry": geometry}


class ValidateStage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_disposable_database()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="curbos-cds-validation-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.bundle = Bundle(self.base / f"synthetic-{self._testMethodName}")
        self.output = self.base / "validation"
        self.output.mkdir(mode=0o700)

    def stage(
        self, *, zones=None, policies=None, areas=None, crs="EPSG:4326", bundle=None
    ):
        bundle = bundle or self.bundle
        if zones is None:
            zones = [curb()]
        bundle.component("zones", envelope("zones", zones))
        if policies is not None:
            bundle.component("policies", envelope("policies", policies))
        if areas is not None:
            bundle.component("areas", envelope("areas", areas))
            bundle.entry("areas")["source_crs"] = "CRS84"
        if crs is not None:
            bundle.entry("zones")["source_crs"] = crs
        bundle.save()
        result = capture(bundle.args())
        self.assertEqual(result["state"], "STAGED", result)
        return UUID(result["batch_id"]), bundle.staging / result["batch_id"]

    def command(self, batch_id, directory, code=None, *, prefix=(), extra=(), env=None):
        entry = ["-m", "data.cds_validate"] if code is None else ["-c", code]
        return subprocess.run(
            [
                *prefix,
                sys.executable,
                *entry,
                "--batch-id",
                str(batch_id),
                "--scope-key",
                _SCOPE,
                "--stage-dir",
                str(directory),
                "--output-root",
                str(self.output),
                *extra,
            ],
            check=False,
            capture_output=True,
            timeout=45,
            env=env,
        )

    def files(self, result):
        return {
            path.name: path.read_bytes()
            for path in (self.output / result["candidate_id"]).iterdir()
        }

    def output_data(self, batch_id, directory):
        result = validate(batch_id, _SCOPE, directory, self.output)
        contents = self.files(result)
        report = parse_json(contents["report.json"], "TEST")
        evidence = [
            parse_json(line, "TEST")
            for line in contents["evidence.ndjson"].splitlines()
        ]
        candidate = parse_json(contents["candidate.json"], "TEST")
        self.assertFalse(result["public_eligible"])
        self.assertFalse(report["public_eligible"])
        self.assertFalse(candidate["public_eligible"])
        self.assertEqual(candidate["candidate_status"], "PREPARED_PRIVATE")
        return result, report, evidence, candidate

    def replace(self, path, data):
        path.chmod(0o600)
        path.write_bytes(data)
        path.chmod(0o400)

    def reanchor(self, batch_id, directory, change):
        """Inject a deliberately inconsistent anchor in this disposable database."""
        path = directory / "report.json"
        report = parse_json(path.read_bytes(), "TEST")
        change(report)
        raw = canonical(report)
        report_sha = digest(raw)
        self.replace(path, raw)
        hashes = {
            name: descriptor["sha256"]
            for name, descriptor in report["stage_files"].items()
        } | {"report.json": report_sha}
        self.replace(
            directory / "SHA256SUMS",
            "".join(f"{sha}  {name}\n" for name, sha in sorted(hashes.items())).encode(
                "ascii"
            ),
        )
        with database.transaction() as connection:
            # Deliberate registry corruption for the validator test only.
            connection.execute(
                "ALTER TABLE sources.import_batch DISABLE TRIGGER protect_batch"
            )
            connection.execute(
                "UPDATE sources.import_batch SET validation_report_sha256 = %s WHERE batch_id = %s",
                (report_sha, batch_id),
            )
            connection.execute(
                "ALTER TABLE sources.import_batch ENABLE TRIGGER protect_batch"
            )

    def failure(self, batch_id, directory, code, *, scope=_SCOPE):
        with self.assertRaises(CaptureError) as raised:
            validate(batch_id, scope, directory, self.output)
        self.assertEqual(raised.exception.code, code)

    def database_contents(self):
        names = (
            ("sources", "source_dataset"),
            ("sources", "raw_artifact"),
            ("sources", "import_batch"),
            ("sources", "import_artifact"),
            ("sources", "qa_issue"),
            ("sources", "dataset_release"),
            ("sources", "active_release"),
            ("sources", "activation_event"),
            ("geo", "release_curb_zone"),
            ("geo", "parking_resource"),
            ("rules", "release_policy_definition"),
            ("rules", "release_zone_policy_link"),
            ("sources", "release_area"),
            ("sources", "release_area_zone"),
        )
        with database.transaction() as connection:
            return {
                name: connection.execute(
                    sql.SQL(
                        "SELECT to_jsonb(r)::text FROM {} AS r ORDER BY to_jsonb(r)::text"
                    ).format(sql.Identifier(*name))
                ).fetchall()
                for name in names
            }

    def test_complete_package_preserves_bytes_and_is_read_only(self):
        source = curb(1, areas=[key(300)])
        batch_id, directory = self.stage(zones=[source], areas=[area(300, [key(1)])])
        original = {p.name: p.read_bytes() for p in directory.iterdir()}
        before = self.database_contents()
        execution = self.command(batch_id, directory)
        self.assertEqual(execution.returncode, 0, execution.stderr)
        result = parse_json(execution.stdout, "TEST")
        files_first = self.files(result)
        retried, report, evidence, candidate = self.output_data(batch_id, directory)
        self.assertEqual(result, retried)
        self.assertEqual(files_first, self.files(retried))
        self.assertEqual(self.database_contents(), before)
        self.assertEqual(
            {p.name: p.read_bytes() for p in directory.iterdir()}, original
        )
        self.assertEqual(
            report["lineage"]["stage_report_sha256"], digest(original["report.json"])
        )
        self.assertEqual(report["lineage"]["scope_key"], _SCOPE)
        self.assertEqual(
            report["lineage"]["artifacts"]["zones"]["declared_source_crs"], "EPSG:4326"
        )
        self.assertTrue(report["lineage"]["geometry_engine"]["postgis"])
        self.assertTrue(report["lineage"]["geometry_engine"]["geos"])
        self.assertEqual(
            report["roles"]["zones"]["dispositions"],
            {"ACCEPTED": 1, "REVIEW_REQUIRED": 0, "EXCLUDED": 0},
        )
        self.assertEqual(evidence[0]["stage_record"]["payload"], source)
        self.assertEqual(evidence[0]["curb_placement"], "UNVERIFIED")
        self.assertEqual(
            candidate["zone_policy_links"],
            [
                {"zone_id": key(1), "policy_id": key(100), "source_position": 0},
            ],
        )
        self.assertEqual(
            candidate["area_zone_links"], [{"zone_id": key(1), "area_id": key(300)}]
        )
        self.assertEqual(files_first["quarantine.ndjson"], b"")
        for line in files_first["SHA256SUMS"].decode("ascii").splitlines():
            sha, name = line.split("  ")
            self.assertEqual(sha, digest(files_first[name]))
            out = self.output / result["candidate_id"] / name
            self.assertEqual(out.stat().st_mode & 0o777, 0o400)

    def test_geometry_qa_separates_warnings_from_exclusions(self):
        cases = [
            curb(),
            curb(
                2,
                geometry={
                    "type": "LineString",
                    "coordinates": [[0, 0], [0, 0], [0, 1]],
                },
            ),
            curb(3, geometry={"type": "LineString", "coordinates": [[0, 0], [0, 0]]}),
            curb(
                4,
                geometry={
                    "type": "LineString",
                    "coordinates": [[0, 0], [2, 2], [0, 2], [2, 0]],
                },
            ),
            curb(5, geometry={"type": "LineString", "coordinates": [[0, 0], [181, 2]]}),
            curb(6, geometry={"type": "Point", "coordinates": [0, 0]}),
            curb(7, geometry={"type": "LineString", "coordinates": []}),
            curb(8) | {"street_side": None, "location_references": {"ref_id": None}},
            curb(9) | {"street_side": "RIGHT"},
        ]
        batch_id, directory = self.stage(zones=cases)
        _, report, evidence, candidate = self.output_data(batch_id, directory)
        zones = evidence[: len(cases)]
        self.assertEqual([row["stage_record"]["payload"] for row in zones], cases)
        self.assertEqual(
            [row["disposition"] for row in zones],
            [
                "ACCEPTED",
                "ACCEPTED",
                "EXCLUDED",
                "REVIEW_REQUIRED",
                "EXCLUDED",
                "EXCLUDED",
                "EXCLUDED",
                "REVIEW_REQUIRED",
                "REVIEW_REQUIRED",
            ],
        )
        for row, reason in zip(
            zones[1:],
            (
                "ZONE_GEOMETRY_REPEATED_VERTEX",
                "ZONE_GEOMETRY_DEGENERATE",
                "ZONE_GEOMETRY_NON_SIMPLE",
                "ZONE_GEOMETRY_INVALID_COORDINATES",
                "ZONE_GEOMETRY_NOT_LINESTRING",
                "ZONE_GEOMETRY_EMPTY",
                "STREET_SIDE_UNKNOWN",
                "SOURCE_STREET_SIDE_CONFLICT",
            ),
            strict=True,
        ):
            self.assertIn(reason, row["reason_codes"])
        self.assertIn("ROAD_REFERENCE_MISSING", zones[7]["reason_codes"])
        self.assertEqual(
            report["roles"]["zones"]["reason_row_counts"][
                "ZONE_GEOMETRY_REPEATED_VERTEX"
            ],
            2,
        )
        self.assertIsNone(
            report["area_membership"]["zones_without_area_or_road_reference"]
        )
        self.assertEqual(
            candidate["accepted_records"]["zones"],
            [
                {"source_id": key(1), "source_index": 0},
                {"source_id": key(2), "source_index": 1},
            ],
        )

    def test_full_validation_without_network_uses_local_postgres_socket(self):
        batch_id, directory = self.stage()
        execution = self.command(
            batch_id,
            directory,
            "import socket; from data.cds_validate import __main__ as cli; "
            "probe = socket.socket(); probe.settimeout(1); "
            "assert probe.connect_ex(('127.0.0.1', 5432)) != 0; probe.close(); "
            "raise SystemExit(cli.main())",
            prefix=offline_command_prefix(),
            extra=("--db-socket-dir", os.environ["CURBOS_TEST_DB_SOCKET"]),
            env=os.environ | {"CURBOS_CAPTURE_DB_PORT": "5432"},
        )
        self.assertEqual(execution.returncode, 0, execution.stderr)
        self.assertEqual(
            parse_json(execution.stdout, "TEST")["state"], "VALIDATION_COMPLETE"
        )

    def test_crs_unknown_remains_review_and_unsupported_is_excluded(self):
        for crs, reason, disposition in (
            (None, "SOURCE_CRS_UNDECLARED", "REVIEW_REQUIRED"),
            ("EPSG:3857", "ZONE_CRS_UNSUPPORTED", "EXCLUDED"),
        ):
            with self.subTest(crs=crs):
                batch_id, directory = self.stage(crs=crs)
                _, _, evidence, _ = self.output_data(batch_id, directory)
                self.assertEqual(evidence[0]["disposition"], disposition)
                self.assertIn(reason, evidence[0]["reason_codes"])

    def test_policy_references_keep_distinct_denominators_and_no_dangling_links(self):
        unusable = policy(102)
        unusable["rules"][0]["user_classes"] = [None]
        cases = [
            curb(1, refs=[key(100), key(100)]),
            curb(2, refs=[key(900), key(900)]),
            curb(3, refs=[key(101)]),
            curb(4, refs=[key(102)]),
            curb(5, refs=["bad-id"]),
        ]
        batch_id, directory = self.stage(
            zones=cases, policies=[policy(), policy(101), policy(101), unusable]
        )
        _, report, evidence, candidate = self.output_data(batch_id, directory)
        self.assertEqual(
            report["policy_references"],
            {
                "declared_entries": 7,
                "invalid_ids": 1,
                "missing_ids": 2,
                "ambiguous_ids": 1,
                "resolved_unique": 3,
                "resolved_but_unusable": 1,
                "zone_rows_with_missing_references": 1,
                "distinct_zone_ids_with_missing_references": 1,
                "candidate_links": 2,
            },
        )
        for row, issue in zip(
            evidence[1:5],
            (
                "POLICY_REFERENCE_NOT_FOUND",
                "POLICY_REFERENCE_AMBIGUOUS",
                "POLICY_REFERENCE_UNUSABLE",
                "POLICY_REFERENCE_INVALID",
            ),
            strict=True,
        ):
            self.assertEqual(row["disposition"], "EXCLUDED")
            self.assertIn(issue, row["reason_codes"])
        self.assertEqual(evidence[3]["stage_record"]["policy_ref_status"], "COMPLETE")
        self.assertEqual(evidence[3]["stage_record"]["policy_parse_status"], "FAILED")
        self.assertEqual(
            candidate["zone_policy_links"],
            [
                {"zone_id": key(1), "policy_id": key(100), "source_position": 0},
                {"zone_id": key(1), "policy_id": key(100), "source_position": 1},
            ],
        )

    def test_area_identity_membership_and_geometry_qa(self):
        cases = [
            curb(1, areas=[key(300), key(301)]),
            curb(2) | {"location_references": {}},
            curb(3, areas=[key(302)]),
            curb(4, areas=[key(303)]),
            curb(5, areas=[key(999), key(304), key(999)]),
        ]
        area_rows = [
            area(300, [key(1)]),
            area(301, [key(1)], {"type": "MultiPolygon", "coordinates": []}),
            area(
                302,
                [key(3)],
                {"type": "MultiLineString", "coordinates": [[[0, 0], [0, 1]]]},
            ),
            area(303, []),
            area(304, []),
            area(304, []),
            area(305, [key(888)]),
            area(
                306,
                [],
                {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [2, 2], [0, 2], [2, 0], [0, 0]]],
                },
            ),
            area(307, [], None),
        ]
        batch_id, directory = self.stage(zones=cases, areas=area_rows)
        _, report, evidence, candidate = self.output_data(batch_id, directory)
        links = report["area_membership"]
        self.assertEqual(
            links["from_zones"],
            {
                "declared_entries": 7,
                "malformed_lists": 0,
                "invalid_id_entries": 0,
                "missing_target_entries": 2,
                "ambiguous_target_entries": 1,
                "duplicate_entries": 1,
                "valid_unique_pairs": 4,
            },
        )
        self.assertEqual(links["from_areas"]["missing_target_entries"], 1)
        self.assertEqual(links["reciprocal_pairs"], 3)
        self.assertEqual(links["omitted_reciprocal_pairs"], 2)
        self.assertEqual(links["zone_only_pairs"], 1)
        self.assertEqual(links["zones_without_area_or_road_reference"], 1)
        self.assertEqual(
            candidate["area_zone_links"], [{"zone_id": key(1), "area_id": key(300)}]
        )
        areas = [row for row in evidence if row["stage_record"]["role"] == "areas"]
        self.assertEqual([row["stage_record"]["payload"] for row in areas], area_rows)
        for index, code in (
            (1, "AREA_GEOMETRY_EMPTY"),
            (2, "AREA_GEOMETRY_MULTILINESTRING"),
            (3, "AREA_MEMBERSHIP_ONE_SIDED"),
            (4, "SOURCE_ID_DUPLICATE"),
            (6, "AREA_ZONE_REFERENCE_NOT_FOUND"),
            (7, "AREA_GEOMETRY_POSTGIS_INVALID"),
            (8, "AREA_GEOMETRY_MISSING"),
        ):
            self.assertIn(code, areas[index]["reason_codes"])

    def test_stage_file_tampering_and_missing_files_fail_closed(self):
        batch_id, directory = self.stage()
        path = directory / "zones.ndjson"
        original = path.read_bytes()
        self.replace(path, original.replace(b"synthetic-road", b"synthetic-fake"))
        self.failure(batch_id, directory, "STAGE_FILE_DIGEST_MISMATCH")
        self.replace(path, original)
        unexpected = directory / "extra.ndjson"
        unexpected.touch()
        self.failure(batch_id, directory, "STAGE_FILE_SET_MISMATCH")
        unexpected.unlink()
        path.unlink()
        self.failure(batch_id, directory, "STAGE_FILE_SET_MISMATCH")
        self.assertFalse(list(self.output.iterdir()))

    def test_symlink_and_path_traversal_fail_closed(self):
        batch_id, directory = self.stage()
        path = directory / "zones.ndjson"
        moved = self.base / "zones.ndjson"
        path.rename(moved)
        path.symlink_to(moved)
        self.failure(batch_id, directory, "STAGE_FILE_UNAVAILABLE_OR_UNSAFE")
        path.unlink()
        moved.rename(path)
        self.failure(batch_id, directory / ".." / directory.name, "UNSAFE_ROOT")
        via_symlink = self.base / "symlink"
        via_symlink.symlink_to(directory, target_is_directory=True)
        process = self.command(batch_id, via_symlink)
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assertEqual(
            parse_json(process.stderr, "TEST")["code"], "VALIDATION_FILESYSTEM_FAILURE"
        )
        self.assertNotIn(str(self.base).encode(), process.stderr)
        checksums = directory / "SHA256SUMS"
        self.replace(
            checksums, checksums.read_bytes().replace(b"zones.ndjson", b"../outside.x")
        )
        self.failure(batch_id, directory, "STAGE_CHECKSUM_MANIFEST_MISMATCH")

    def test_stage_version_record_counts_and_provenance_are_independently_checked(self):
        for suffix, change, code in (
            (
                "version",
                lambda report: report.update(stage_schema_version=1),
                "UNSUPPORTED_STAGE_SCHEMA",
            ),
            (
                "count",
                lambda report: report["components"]["zones"].update(record_count=0),
                "STAGE_RECORD_COUNTS_MISMATCH",
            ),
            (
                "artifact",
                lambda report: report["components"]["zones"].update(sha256="0" * 64),
                "STAGE_ARTIFACT_MISMATCH",
            ),
            (
                "candidate",
                lambda report: report.update(public_eligible=True),
                "STAGE_BATCH_IDENTITY_MISMATCH",
            ),
            (
                "policy",
                lambda report: report.update(
                    zone_policy_parse_status_counts={"FAILED": 1}
                ),
                "STAGE_POLICY_QA_MISMATCH",
            ),
        ):
            with self.subTest(suffix=suffix):
                other = Bundle(self.base / f"synthetic-{suffix}")
                batch_id, directory = self.stage(bundle=other)
                self.reanchor(batch_id, directory, change)
                self.failure(batch_id, directory, code)
        self.assertFalse(list(self.output.iterdir()))

    def test_batch_scope_and_artifact_lineage_cannot_be_mixed(self):
        first, directory = self.stage()
        second, other_dir = self.stage(
            bundle=Bundle(self.base / "synthetic-other"), zones=[curb(2)]
        )
        self.failure(first, directory, "BATCH_SCOPE_MISMATCH", scope="synthetic-wrong")
        self.failure(first, other_dir, "STAGE_REPORT_DIGEST_MISMATCH")
        first_result, _, _, _ = self.output_data(first, directory)
        second_result, _, _, _ = self.output_data(second, other_dir)
        self.assertNotEqual(first_result["candidate_id"], second_result["candidate_id"])

        with database.transaction() as connection:
            connection.execute(
                "ALTER TABLE sources.import_artifact DISABLE TRIGGER protect_batch_artifacts"
            )
            connection.execute(
                """
                UPDATE sources.import_artifact AS j
                SET artifact_id = other.artifact_id
                FROM sources.import_artifact AS other
                WHERE j.batch_id = %s AND other.batch_id = %s
                  AND j.component_role = 'zones' AND other.component_role = 'zones'
                """,
                (first, second),
            )
            connection.execute(
                "ALTER TABLE sources.import_artifact ENABLE TRIGGER protect_batch_artifacts"
            )
        self.failure(first, directory, "ARTIFACT_LINEAGE_MISMATCH")

    def test_crash_recovery_and_existing_candidate_corruption(self):
        batch_id, directory = self.stage()
        process = self.command(
            batch_id,
            directory,
            code=(
                "import os; from data.cds_validate import __main__ as cmd; "
                "cmd.files.promote = lambda *args: os._exit(96); cmd.main()"
            ),
        )
        self.assertEqual(process.returncode, 96, process.stderr)
        scratch = next(self.output.glob(".*.partial"))
        self.assertTrue((scratch / "report.json").is_file())
        self.assertFalse(
            [path for path in self.output.iterdir() if not path.name.startswith(".")]
        )
        recovered, _, _, _ = self.output_data(batch_id, directory)
        self.assertFalse(scratch.exists())
        path = self.output / recovered["candidate_id"] / "report.json"
        corrupted = path.read_bytes() + b"corruption"
        self.replace(path, corrupted)
        self.failure(batch_id, directory, "CANDIDATE_FILE_MISMATCH")
        self.assertEqual(path.read_bytes(), corrupted)
