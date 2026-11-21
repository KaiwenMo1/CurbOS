"""Offline PR-07 assessment tests with invented data and disposable PostgreSQL."""

import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from secrets import token_urlsafe
from unittest.mock import patch
from uuid import UUID

import psycopg
from jsonschema import Draft202012Validator, FormatChecker
from psycopg import sql

from data.cds_capture import database
from data.cds_capture.__main__ import run as capture
from data.cds_capture.manifest import CaptureError, canonical, digest, parse_json
from data.cds_publish.__main__ import run as register
from data.cds_readiness.__main__ import run
from data.cds_validate.__main__ import prepare, run as validate
from fixtures import Bundle, envelope, key, prepare_disposable_database
from test_validate import area, curb

_SCOPE = "synthetic-readiness"
_READER = "synthetic_readiness_reader"
_ASSESSOR = Path(__file__).resolve().parents[2] / "data/cds_readiness"
_SCHEMA = Draft202012Validator(
    parse_json((_ASSESSOR / "readiness.schema.json").read_bytes(), "TEST"),
    format_checker=FormatChecker(),
)


class Readiness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_disposable_database()
        cls.password = token_urlsafe(24)
        with database.transaction() as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(_READER), sql.Literal(cls.password)
                )
            )
            grants = (
                (_ASSESSOR / "reader_privileges.sql")
                .read_text()
                .replace(':"reader"', sql.Identifier(_READER).as_string(admin))
            )
            admin.execute(grants)

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="curbos-synthetic-readiness-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.validation = self.root / "validation"
        self.validation.mkdir(mode=0o700)
        self.output = self.root / "assessment"
        self.output.mkdir(mode=0o700)

    def fixture(
        self, *, zones=None, policies=None, areas=None, scope=_SCOPE, label="fixture"
    ):
        bundle = Bundle(
            self.root / f"synthetic-{self._testMethodName}-{label}", scope=scope
        )
        bundle.component(
            "zones", envelope("zones", zones if zones is not None else [curb()])
        )
        bundle.entry("zones")["source_crs"] = "EPSG:4326"
        if policies is not None:
            bundle.component("policies", envelope("policies", policies))
        if areas is not None:
            bundle.component("areas", envelope("areas", areas))
            bundle.entry("areas")["source_crs"] = "CRS84"
        bundle.save()
        with database.transaction() as admin:
            admin.execute(
                "INSERT INTO sources.publication_scope (scope_key, display_name) "
                "VALUES (%s, 'Synthetic readiness') ON CONFLICT DO NOTHING",
                (scope,),
            )
        staged = capture(bundle.args())
        self.assertEqual(staged["state"], "STAGED", staged)
        batch_id = UUID(staged["batch_id"])
        stage_dir = bundle.staging / str(batch_id)
        candidate = validate(batch_id, scope, stage_dir, self.validation)
        return {
            "batch_id": batch_id,
            "scope_key": scope,
            "artifact_root": bundle.artifact,
            "stage_dir": stage_dir,
            "candidate_dir": self.validation / candidate["candidate_id"],
            "expected_report_sha": candidate["report_sha256"],
            "output_root": self.output,
        }

    def assess(self, params):
        with patch.dict(os.environ, {"PGUSER": _READER, "PGPASSWORD": self.password}):
            return run(**params)

    def report(self, params):
        receipt = self.assess(params)
        self.assertFalse(receipt["public_eligible"])
        directory = params["output_root"] / receipt["report_directory"]
        raw = (directory / "readiness.json").read_bytes()
        self.assertEqual(receipt["report_sha256"], digest(raw))
        obj = parse_json(raw, "TEST")
        _SCHEMA.validate(obj)
        return receipt, obj

    def failed(self, params, code):
        with self.assertRaises(CaptureError) as caught:
            self.assess(params)
        self.assertEqual(caught.exception.code, code)
        self.assertFalse(any(item.is_dir() for item in params["output_root"].iterdir()))

    def replace(self, path, value):
        path.chmod(0o600)
        path.write_bytes(value)
        path.chmod(0o400)

    def private_json(self, filename, content):
        path = self.root / filename
        path.write_bytes(canonical(content))
        path.chmod(0o600)
        return path

    def state(self):
        names = (
            ("sources", "source_dataset"),
            ("sources", "import_batch"),
            ("sources", "import_artifact"),
            ("sources", "raw_artifact"),
            ("sources", "publication_scope"),
            ("sources", "dataset_release"),
            ("sources", "active_release"),
            ("sources", "activation_event"),
            ("sources", "qa_issue"),
            ("publication", "release_evidence"),
            ("publication", "release_verification"),
            ("publication", "release_approval"),
            ("publication", "synthetic_fixture"),
            ("geo", "release_curb_zone"),
            ("rules", "release_policy_definition"),
            ("rules", "release_zone_policy_link"),
            ("sources", "release_area"),
            ("sources", "release_area_zone"),
        )
        with database.transaction() as admin:
            return {
                name: admin.execute(
                    sql.SQL(
                        "SELECT to_jsonb(r)::text FROM {} r ORDER BY to_jsonb(r)::text"
                    ).format(sql.Identifier(*name))
                ).fetchall()
                for name in names
            }

    def test_complete_deterministic_report_and_no_database_mutation(self):
        params = self.fixture()
        before = self.state()

        def read_only(connection, *args):
            self.assertEqual(
                connection.execute("SHOW transaction_read_only").fetchone(), ("on",)
            )
            self.assertEqual(
                connection.execute("SHOW transaction_isolation").fetchone(),
                ("repeatable read",),
            )
            return prepare(connection, *args)

        with patch("data.cds_readiness.__main__.prepare", side_effect=read_only):
            receipt, report = self.report(params)
        self.assertEqual(report["outcomes"]["TECHNICAL_READINESS"]["status"], "PASS")
        self.assertEqual(report["outcomes"]["EVIDENCE_READINESS"]["status"], "BLOCKED")
        self.assertEqual(
            report["outcomes"]["PUBLICATION_READINESS"]["status"], "BLOCKED"
        )
        self.assertEqual(report["recommendation"], "NO_GO")
        self.assertEqual(report["source"]["registered_rights_status"], "UNKNOWN")
        self.assertEqual(
            report["checklist"]["geometry_redistribution"]["state"], "UNKNOWN"
        )
        self.assertEqual(report["coverage"]["comparison_status"], "NOT_ASSESSED")
        self.assertEqual(report["placement"]["physical_placement"], "UNKNOWN")
        self.assertEqual(report["parking_evidence"]["parking_legality"], "UNKNOWN")
        self.assertEqual(report["registration"]["status"], "NOT_REGISTERED")
        self.assertEqual(report["qa"]["area_geometry"]["status"], "NOT_ASSESSED")
        self.assertIsNone(report["qa"]["comparable_metrics"]["area_source_rows"])
        self.assertEqual(report["historical_comparison"]["status"], "NOT_ASSESSED")
        directory = self.output / receipt["report_directory"]
        original = {p.name: p.read_bytes() for p in directory.iterdir()}
        self.assertEqual(self.assess(params), receipt)
        self.assertEqual(
            {p.name: p.read_bytes() for p in directory.iterdir()}, original
        )
        self.assertEqual(
            set(original), {"readiness.json", "READINESS_REPORT.md", "SHA256SUMS"}
        )
        self.assertIn(b"NO-GO", original["READINESS_REPORT.md"])
        self.assertNotIn(b"synthetic-cds.invalid", original["readiness.json"])
        self.assertNotIn(b"coordinates", original["readiness.json"])
        self.assertNotIn(self.password.encode(), original["readiness.json"])
        self.assertEqual(self.state(), before)

    def test_stage_corruption_and_wrong_batch_or_scope_fail_without_mutation(self):
        params = self.fixture()
        with self.subTest("wrong batch"):
            self.failed(params | {"batch_id": UUID(int=0)}, "BATCH_NOT_FOUND")
        with self.subTest("wrong scope"):
            self.failed(
                params | {"scope_key": "synthetic-wrong"}, "BATCH_SCOPE_MISMATCH"
            )
        before = self.state()
        report = params["stage_dir"] / "report.json"
        self.replace(report, report.read_bytes() + b" ")
        with self.subTest("stage report corruption"):
            self.failed(params, "STAGE_REPORT_DIGEST_MISMATCH")
        self.assertEqual(self.state(), before)

    def test_candidate_digest_cross_batch_and_recomputed_file_mismatch(self):
        params = self.fixture()
        other = self.fixture(label="other")
        self.failed(
            params | {"expected_report_sha": "0" * 64},
            "CANDIDATE_REPORT_DIGEST_MISMATCH",
        )
        self.failed(
            params | {"candidate_dir": other["candidate_dir"]},
            "CANDIDATE_IDENTITY_MISMATCH",
        )
        candidate = params["candidate_dir"] / "candidate.json"
        self.replace(candidate, candidate.read_bytes() + b" ")
        self.failed(params, "CANDIDATE_FILE_MISMATCH")

    def test_missing_or_corrupted_raw_artifact(self):
        params = self.fixture()
        raw = next(
            path
            for path in params["artifact_root"].iterdir()
            if not path.name.startswith(".")
        )
        content = raw.read_bytes()
        self.replace(raw, bytes([content[0] ^ 1]) + content[1:])
        self.failed(params, "RAW_ARTIFACT_DIGEST_MISMATCH")
        raw.unlink()
        self.failed(params, "RAW_ARTIFACT_UNAVAILABLE_OR_UNSAFE")

    def test_source_findings_with_row_denominators_and_no_raw_payloads(self):
        params = self.fixture(
            zones=[
                curb(1),
                curb(2),
                curb(2) | {"raw_private_note": "DO_NOT_EMIT_PRIVATE_FIXTURE"},
                curb(3, refs=[key(999)]),
                curb(4, refs=[key(101)]),
                curb(5) | {"street_side": None},
                curb(
                    6,
                    geometry={
                        "type": "LineString",
                        "coordinates": [[Decimal("0.123456789123456789"), 0], [0, 1]],
                    },
                ),
                curb(
                    7,
                    geometry={
                        "type": "LineString",
                        "coordinates": [[0, 0], [0, 0], [0, 1]],
                    },
                ),
                curb(8, areas=[key(301)]),
                curb(9)
                | {
                    "curb_zone_id": "DO_NOT_EMIT_PRIVATE_FIXTURE",
                    "location_references": None,
                },
            ],
            policies=[
                {
                    "curb_policy_id": key(100),
                    "rules": [{"activity": "synthetic", "user_classes": []}],
                },
                {
                    "curb_policy_id": key(101),
                    "rules": [{"activity": "synthetic", "user_classes": [None]}],
                },
            ],
            areas=[
                area(301, []),
                area(302, [key(999)], {"type": "MultiPolygon", "coordinates": []}),
                area(
                    303,
                    [],
                    {"type": "MultiLineString", "coordinates": [[[0, 0], [0, 1]]]},
                ),
            ],
        )
        receipt, obj = self.report(params)
        qa = obj["qa"]
        zones, policies, areas = (
            qa["roles"][role] for role in ("zones", "policies", "areas")
        )
        self.assertEqual(
            (zones["input_rows"], policies["input_rows"], areas["input_rows"]),
            (10, 2, 3),
        )
        for group in qa["roles"].values():
            self.assertEqual(sum(group["dispositions"].values()), group["input_rows"])
        self.assertEqual(zones["reason_row_counts"]["SOURCE_ID_DUPLICATE"], 2)
        self.assertEqual(zones["reason_row_counts"]["SOURCE_ID_INVALID"], 1)
        self.assertEqual(zones["reason_row_counts"]["ZONE_GEOMETRY_REPEATED_VERTEX"], 1)
        self.assertEqual(zones["reason_row_counts"]["STREET_SIDE_UNKNOWN"], 1)
        self.assertGreater(zones["dispositions"]["REVIEW_REQUIRED"], 0)
        self.assertEqual(qa["policy_structure"]["failed"], 1)
        self.assertEqual(
            qa["affected_records"]["policies"][0]["unsupported_policy_shape"][
                "list_entries"
            ][0]["user_class_entry_types"],
            {"NoneType": 1},
        )
        self.assertEqual(qa["policy_references"]["missing_ids"], 1)
        self.assertEqual(qa["policy_references"]["resolved_but_unusable"], 1)
        self.assertEqual(
            qa["policy_references"]["zone_rows_with_unusable_references"], 1
        )
        self.assertEqual(qa["policy_usage"]["legal_semantics"], "UNKNOWN")
        issues = {row["source_index"]: row for row in qa["affected_records"]["zones"]}
        self.assertEqual(
            issues[3]["missing_policy_references"][0]["source_policy_id"], key(999)
        )
        self.assertEqual(
            issues[4]["unusable_policy_references"][0]["source_policy_id"], key(101)
        )
        self.assertEqual(issues[9]["source_id"], None)
        self.assertEqual(qa["area_membership"]["zone_only_pairs"], 1)
        self.assertEqual(
            qa["area_membership"]["from_areas"]["missing_target_entries"], 1
        )
        self.assertEqual(areas["reason_row_counts"]["AREA_GEOMETRY_EMPTY"], 1)
        self.assertEqual(areas["reason_row_counts"]["AREA_GEOMETRY_MULTILINESTRING"], 1)
        self.assertEqual(qa["projection"]["projection_geometry_exclusions"]["zones"], 1)
        self.assertEqual(
            qa["projection"]["geometry_exclusions"][0]["source_id"], key(6)
        )
        self.assertNotIn(
            b"DO_NOT_EMIT_PRIVATE_FIXTURE",
            (self.output / receipt["report_directory"] / "readiness.json").read_bytes(),
        )

    def test_known_denial_and_independent_placement_are_explicit_blockers(self):
        params = self.fixture()
        initial, obj = self.report(params)
        with database.transaction() as admin:
            admin.execute(
                "UPDATE sources.source_dataset SET rights_status = 'DENIED' WHERE dataset_id = %s",
                (UUID(obj["lineage"]["dataset_id"]),),
            )
        evidence = self.private_json(
            "review.json",
            {
                "schema_version": 1,
                "binding": obj["subject"],
                "placement_claim": "INDEPENDENTLY_VERIFIED",
                "items": {
                    "geometry_redistribution": {
                        "state": "BLOCKED",
                        "evidence_ref": "evidence:synthetic-denial",
                    }
                },
            },
        )
        next_receipt, new = self.report(params | {"evidence_file": evidence})
        self.assertNotEqual(
            initial["report_directory"], next_receipt["report_directory"]
        )
        blockers = {
            item["code"] for item in new["outcomes"]["PUBLICATION_READINESS"]["reasons"]
        }
        self.assertTrue(
            {
                "SOURCE_RIGHTS_BLOCKED",
                "RIGHTS_GEOMETRY_REDISTRIBUTION_BLOCKED",
                "INDEPENDENT_COVERAGE_REVIEW_MISSING_OR_BLOCKED",
                "INDEPENDENT_PLACEMENT_REVIEW_MISSING_OR_BLOCKED",
                "PRODUCTION_PUBLICATION_PROCESS_UNAUTHORIZED",
                "REAL_WORLD_PUBLICATION_AUTHORIZATION_MISSING",
            }.issubset(blockers)
        )
        self.assertEqual(
            new["parking_evidence"]["authoritative_legal_backing"], "UNKNOWN"
        )

    def test_review_rejects_foreign_binding_and_malformed_reference(self):
        params = self.fixture()
        original = params["candidate_dir"] / "report.json"
        candidate = parse_json(original.read_bytes(), "TEST")
        binding = {
            key: candidate["lineage"][key]
            for key in ("batch_id", "scope_key", "stage_report_sha256")
        } | {
            "candidate_id": candidate["candidate_id"],
            "candidate_report_sha256": params["expected_report_sha"],
        }
        review = self.private_json(
            "review.json",
            {
                "schema_version": 1,
                "binding": binding,
                "items": {
                    "geometry_redistribution": {
                        "state": "BLOCKED",
                        "evidence_ref": "https://secret.invalid/?token=private",
                    }
                },
            },
        )
        self.failed(params | {"evidence_file": review}, "INVALID_EVIDENCE_REFERENCE")
        review = self.private_json(
            "review.json",
            {
                "schema_version": 1,
                "items": {},
                "binding": binding | {"batch_id": key(9)},
            },
        )
        self.failed(params | {"evidence_file": review}, "EVIDENCE_BINDING_MISMATCH")

    def test_geometry_only_boundary_and_bound_registration(self):
        params = self.fixture(
            zones=[
                curb(1),
                curb(
                    2, geometry={"type": "LineString", "coordinates": [[0, 0], [0, 5]]}
                ),
            ],
            scope="synthetic-readiness-boundary",
        )
        with database.transaction() as admin:
            admin.execute(
                "UPDATE sources.publication_scope SET reviewed_geom = public.ST_Multi("
                "public.ST_MakeEnvelope(-1,-1,1,2,4326)) WHERE scope_key = %s",
                (params["scope_key"],),
            )
        receipt = register(
            *(
                params[key]
                for key in (
                    "batch_id",
                    "scope_key",
                    "stage_dir",
                    "candidate_dir",
                    "expected_report_sha",
                )
            )
        )
        before = self.state()
        _, report = self.report(params)
        self.assertEqual(report["registration"]["status"], "CANDIDATE")
        self.assertEqual(report["registration"]["release_id"], receipt["release_id"])
        self.assertEqual(
            report["registration"]["projection_plan_sha256"], receipt["plan_sha256"]
        )
        self.assertFalse(report["registration"]["is_active_pointer_target"])
        coverage = report["coverage"]
        self.assertEqual(coverage["comparison_status"], "BOUNDARY_GEOMETRY_ONLY")
        self.assertEqual(coverage["scope_review_status"], "UNREVIEWED")
        self.assertEqual(coverage["denominator_projected_zone_lines"], 2)
        self.assertEqual(coverage["fully_covered"], 1)
        self.assertEqual(coverage["intersecting_not_covered"], 1)
        self.assertEqual(coverage["not_fully_covered_zone_ids"], [key(2)])
        self.assertEqual(self.state(), before)

    def test_history_compares_only_exact_component_and_version_basis(self):
        params = self.fixture(
            areas=[area(301, [], {"type": "MultiPolygon", "coordinates": []})]
        )
        _, initial = self.report(params)
        basis = initial["reproducibility"]["comparison_basis"]
        baseline = self.private_json(
            "baseline.json",
            {
                "schema_version": 1,
                "evidence_ref": "evidence:synthetic-audit",
                "basis": basis,
                "metrics": {"zone_source_rows": 2, "area_source_rows": 1},
                "areas": {
                    key(301): {"geometry_type": "MultiPolygon", "empty_geometry": True}
                },
            },
        )
        _, report = self.report(params | {"baseline_file": baseline})
        compare = report["historical_comparison"]
        self.assertEqual(
            compare["metrics"]["zone_source_rows"],
            {"expected": 2, "observed": 1, "status": "DIFFERENT"},
        )
        self.assertEqual(compare["areas"][key(301)]["status"], "MATCH")
        baseline = self.private_json(
            "baseline.json",
            {
                "schema_version": 1,
                "evidence_ref": "evidence:synthetic-audit",
                "basis": basis | {"adapter_version": "other"},
                "metrics": {"zone_source_rows": 2},
                "areas": {},
            },
        )
        _, report = self.report(params | {"baseline_file": baseline})
        self.assertEqual(
            report["historical_comparison"]["reason"],
            "AUDIT_SNAPSHOT_OR_VERSION_MISMATCH",
        )

    def test_interrupted_report_write_recovers_and_retained_corruption_is_rejected(
        self,
    ):
        params = self.fixture()
        before = self.state()
        with patch(
            "data.cds_readiness.__main__.files.promote",
            side_effect=OSError("synthetic failure"),
        ):
            with self.assertRaises(OSError):
                self.assess(params)
        self.assertFalse(any(item.is_dir() for item in self.output.iterdir()))
        lock = next(self.output.iterdir())
        prefix = lock.name.removesuffix(".lock")
        leftover = self.output / f"{prefix}.partial"
        leftover.mkdir(mode=0o700)
        (leftover / "readiness.json").write_bytes(b"interrupted")
        result, _ = self.report(params)
        self.assertFalse(leftover.exists())
        retained = self.output / result["report_directory"] / "readiness.json"
        self.replace(retained, retained.read_bytes() + b" ")
        with self.assertRaisesRegex(CaptureError, "RETAINED_REPORT_MISMATCH"):
            self.assess(params)
        self.assertEqual(self.state(), before)

    def test_reader_cannot_mutate_or_execute_publication(self):
        with patch.dict(os.environ, {"PGUSER": _READER, "PGPASSWORD": self.password}):
            for statement in (
                "UPDATE sources.source_dataset SET rights_status = 'APPROVED'",
                "UPDATE sources.dataset_release SET status = 'FROZEN'",
                "UPDATE sources.active_release SET release_id = NULL",
                "INSERT INTO sources.activation_event DEFAULT VALUES",
                "INSERT INTO publication.synthetic_fixture DEFAULT VALUES",
                "SELECT publication.register_candidate(NULL,NULL,NULL,NULL,NULL)",
                "SELECT publication.verify_candidate(NULL,NULL,NULL,NULL,NULL)",
                "SELECT publication.approve_release(NULL,NULL)",
                "SELECT publication.freeze_release(NULL)",
                "SELECT publication.change_pointer(NULL,NULL,NULL,NULL,NULL,NULL)",
            ):
                with database.transaction() as reader:
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        reader.execute(statement)
