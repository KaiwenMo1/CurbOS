"""PR-04 publication tests. All data and logins belong to the disposable project."""

import os
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from secrets import token_urlsafe
from uuid import UUID
from unittest.mock import patch

import psycopg
from psycopg import sql

from data.cds_capture import database
from data.cds_capture.__main__ import run as capture
from data.cds_capture.manifest import CaptureError, canonical, digest, parse_json
from data.cds_publish.__main__ import register
from data.cds_validate.__main__ import run as validate
from fixtures import Bundle, envelope, key, prepare_disposable_database
from test_validate import area, curb

_BOUNDARY = "MULTIPOLYGON (((-1 -1,3 -1,3 3,-1 3,-1 -1)))"


class Publication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_disposable_database()
        cls.passwords = {}
        with database.transaction() as admin:
            for kind in ("registrar", "reviewer", "operator", "app"):
                user = f"synthetic_pr04_{kind}"
                password = cls.passwords[kind] = token_urlsafe(24)
                admin.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(user), sql.Literal(password)
                    )
                )
                if kind == "app":
                    admin.execute(
                        sql.SQL("GRANT SELECT ON public.goose_db_version TO {}").format(
                            sql.Identifier(user)
                        )
                    )
                else:
                    admin.execute(
                        sql.SQL("GRANT {} TO {}").format(
                            sql.Identifier(f"curbos_publication_{kind}"),
                            sql.Identifier(user),
                        )
                    )

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="curbos-synthetic-publication-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scope = (
            f"synthetic-{self.root.name.removeprefix('curbos-synthetic-publication-')}"
        )
        self.count = 0
        self.output = self.root / "validation"
        self.output.mkdir(mode=0o700)

    def user(self, kind):
        return psycopg.connect(
            host="127.0.0.1",
            port=os.environ["CURBOS_CAPTURE_DB_PORT"],
            dbname="curbos",
            user=f"synthetic_pr04_{kind}",
            password=self.passwords[kind],
            sslmode="disable",
            connect_timeout=5,
        )

    def candidate(self, *, scope=None, zones=None, areas=None, production_like=False):
        scope = scope or self.scope
        self.count += 1
        bundle = Bundle(
            self.root / f"synthetic-fixture-{self.count}-{self.scope}", scope=scope
        )
        if production_like:
            # Simulate an unenrollable profile using invented source bytes only.
            bundle.manifest["source_profile"] = "synthetic-production-like"
        bundle.component(
            "zones", envelope("zones", zones if zones is not None else [curb()])
        )
        bundle.entry("zones")["source_crs"] = "EPSG:4326"
        if areas is not None:
            bundle.component("areas", envelope("areas", areas))
            bundle.entry("areas")["source_crs"] = "CRS84"
        bundle.save()
        with database.transaction() as admin:
            admin.execute(
                "INSERT INTO sources.publication_scope (scope_key, display_name) "
                "VALUES (%s, 'Synthetic test scope') ON CONFLICT DO NOTHING",
                (scope,),
            )
        captured = capture(bundle.args())
        self.assertEqual(captured["state"], "STAGED", captured)
        batch = UUID(captured["batch_id"])
        stage_dir = bundle.staging / str(batch)
        candidate = validate(batch, scope, stage_dir, self.output)
        directory = self.output / candidate["candidate_id"]
        lineage = parse_json((directory / "report.json").read_bytes(), "TEST")[
            "lineage"
        ]
        return {
            "batch_id": batch,
            "scope_key": scope,
            "stage_dir": stage_dir,
            "candidate_dir": directory,
            "expected_report_sha": candidate["report_sha256"],
        }, lineage

    def register(self, params):
        with patch.dict(
            os.environ,
            {
                "PGUSER": "synthetic_pr04_registrar",
                "PGPASSWORD": self.passwords["registrar"],
            },
        ):
            return register(**params)

    def fixture_gates(self, params, lineage, *, rights=True, scope=True, enrolled=True):
        with database.transaction() as admin:
            if rights:
                admin.execute(
                    "UPDATE sources.source_dataset SET rights_status = 'APPROVED', "
                    "rights_reference = 'fixture:dataset-rights' WHERE dataset_id = %s",
                    (UUID(lineage["dataset_id"]),),
                )
            if scope:
                admin.execute(
                    "UPDATE sources.publication_scope SET review_status = 'APPROVED', "
                    "reviewed_at = clock_timestamp(), reviewed_geom = public.ST_GeomFromText(%s, 4326) "
                    "WHERE scope_key = %s",
                    (_BOUNDARY, params["scope_key"]),
                )
            if enrolled:
                admin.execute(
                    "INSERT INTO publication.synthetic_fixture VALUES (%s, %s, %s, %s)",
                    (
                        params["batch_id"],
                        params["scope_key"],
                        UUID(lineage["dataset_id"]),
                        lineage["stage_report_sha256"],
                    ),
                )

    def evidence(self, release, lineage):
        return {
            "candidate_report_sha256": release["candidate_report_sha256"],
            "plan_sha256": release["plan_sha256"],
            "artifact_rights": {
                value["artifact_id"]: "fixture:artifact-rights"
                for value in lineage["artifacts"].values()
            },
            "review_exclusions": {
                name: "fixture:record-withheld" for name in release["review_required"]
            },
        } | {
            f"{gate}_ref": f"fixture:{gate}"
            for gate in ("qa", "rights", "scope", "coverage", "placement", "exclusion")
        }

    def approve(self, release, evidence):
        with self.user("reviewer") as connection:
            connection.execute(
                "SELECT publication.approve_release(%s, %s::jsonb)",
                (UUID(release["release_id"]), canonical(evidence).decode("ascii")),
            )

    def freeze(self, release):
        with self.user("reviewer") as connection:
            connection.execute(
                "SELECT publication.freeze_release(%s)", (UUID(release["release_id"]),)
            )

    def frozen(self, scope=None, **kwargs):
        params, lineage = self.candidate(scope=scope, **kwargs)
        release = self.register(params)
        self.fixture_gates(params, lineage)
        self.approve(release, self.evidence(release, lineage))
        self.freeze(release)
        return UUID(release["release_id"])

    def change(
        self,
        target,
        *,
        expected=0,
        action="ACTIVATE",
        scope=None,
        request_key=None,
        reason="synthetic reason",
    ):
        with self.user("operator") as connection:
            return connection.execute(
                "SELECT publication.change_pointer(%s, %s, %s, %s, %s, %s)",
                (
                    scope or self.scope,
                    target,
                    expected,
                    action,
                    reason,
                    request_key or f"{self.scope}-{expected}-{action}",
                ),
            ).fetchone()[0]

    def pointer(self, scope=None):
        with database.transaction() as admin:
            return admin.execute(
                "SELECT release_id, pointer_version FROM sources.active_release WHERE scope_key = %s",
                (scope or self.scope,),
            ).fetchone()

    def events(self):
        with database.transaction() as admin:
            return admin.execute(
                "SELECT from_release_id, to_release_id, action, pointer_version_after "
                "FROM sources.activation_event WHERE scope_key = %s ORDER BY pointer_version_after",
                (self.scope,),
            ).fetchall()

    def expect_db_error(self, code, callback, state=None):
        with self.assertRaises(psycopg.Error) as error:
            callback()
        self.assertEqual(error.exception.diag.message_primary, code)
        if state:
            self.assertEqual(error.exception.sqlstate, state)

    def tamper(self, params, update):
        directory = params["candidate_dir"]
        candidate_path = directory / "candidate.json"
        candidate = parse_json(candidate_path.read_bytes(), "TEST")
        update(candidate)
        raw = canonical(candidate)
        report_path = directory / "report.json"
        report = parse_json(report_path.read_bytes(), "TEST")
        report["output_files"]["candidate.json"] = {
            "sha256": digest(raw),
            "byte_size": len(raw),
        }
        report_raw = canonical(report)
        sums = {name: value["sha256"] for name, value in report["output_files"].items()}
        sums["report.json"] = digest(report_raw)
        for path, content in (
            (candidate_path, raw),
            (report_path, report_raw),
            (
                directory / "SHA256SUMS",
                "".join(
                    f"{value}  {name}\n" for name, value in sorted(sums.items())
                ).encode("ascii"),
            ),
        ):
            path.chmod(0o600)
            path.write_bytes(content)
            path.chmod(0o400)
        return params | {"expected_report_sha": digest(report_raw)}

    def test_candidate_exact_lineage_and_idempotent_registration(self):
        params, lineage = self.candidate(
            zones=[curb(1, areas=[key(300)])], areas=[area(300, [key(1)])]
        )
        release = self.register(params)
        self.assertEqual(self.register(params), release)
        self.assertEqual(release["status"], "VALIDATED")
        with database.transaction() as admin:
            row = admin.execute(
                "SELECT b.batch_id, b.scope_key, e.lineage, e.registered_by, "
                "z.raw_artifact_id, z.geometry_evidence, z.resource_id, z.geometry_sha256 "
                "FROM sources.dataset_release b JOIN publication.release_evidence e USING (release_id) "
                "JOIN geo.release_curb_zone z USING (release_id) WHERE b.release_id = %s",
                (UUID(release["release_id"]),),
            ).fetchone()
            links = admin.execute(
                "SELECT source_area_id, source_zone_id FROM sources.release_area_zone WHERE release_id = %s",
                (UUID(release["release_id"]),),
            ).fetchall()
        self.assertEqual(
            row,
            (
                params["batch_id"],
                self.scope,
                lineage,
                "synthetic_pr04_registrar",
                UUID(lineage["artifacts"]["zones"]["artifact_id"]),
                "SOURCE_REPORTED",
                None,
                digest(canonical(curb()["geometry"])),
            ),
        )
        self.assertEqual(links, [(key(300), key(1))])
        self.assertIsNone(self.pointer())

    def test_corrupted_digest_fails_closed(self):
        params, _ = self.candidate()
        with self.assertRaisesRegex(CaptureError, "CANDIDATE_REPORT_DIGEST_MISMATCH"):
            self.register(params | {"expected_report_sha": "0" * 64})
        self.assertIsNone(self.pointer())

    def test_cross_batch_and_scope_rejected(self):
        params, _ = self.candidate()
        other, _ = self.candidate()
        with self.assertRaisesRegex(CaptureError, "CANDIDATE_IDENTITY_MISMATCH"):
            self.register(other | {"candidate_dir": params["candidate_dir"]})
        with self.assertRaisesRegex(CaptureError, "BATCH_SCOPE_MISMATCH"):
            self.register(params | {"scope_key": "synthetic-other"})
        self.assertIsNone(self.pointer())

    def test_missing_policy_link_fails_even_with_new_checksums(self):
        params, _ = self.candidate()
        params = self.tamper(
            params, lambda candidate: candidate["zone_policy_links"].clear()
        )
        with self.assertRaisesRegex(CaptureError, "CANDIDATE_FILE_MISMATCH"):
            self.register(params)
        self.assertIsNone(self.pointer())

    def test_dangling_area_link_fails_even_with_new_checksums(self):
        params, _ = self.candidate(
            zones=[curb(1, areas=[key(300)])], areas=[area(300, [key(1)])]
        )
        params = self.tamper(
            params,
            lambda candidate: candidate["area_zone_links"][0].update(area_id=key(999)),
        )
        with self.assertRaisesRegex(CaptureError, "CANDIDATE_FILE_MISMATCH"):
            self.register(params)

    def test_reviewed_exclusion_and_unrepresentable_line_are_withheld(self):
        precise = {
            "type": "LineString",
            "coordinates": [[Decimal("0.123456789123456789"), 0], [0, 1]],
        }
        params, lineage = self.candidate(
            zones=[
                curb(1),
                curb(2) | {"street_side": None},
                curb(3, geometry=precise),
            ]
        )
        release = self.register(params)
        self.fixture_gates(params, lineage)
        self.assertEqual(release["review_required"], ["zones:1"])
        self.assertEqual(release["summary"]["projected"]["zones"], 1)
        self.assertEqual(
            release["summary"]["projection_geometry_exclusions"]["zones"], 1
        )
        evidence = self.evidence(release, lineage)
        self.expect_db_error(
            "REVIEW_DISPOSITION_REQUIRED",
            lambda: self.approve(release, evidence | {"review_exclusions": {}}),
        )
        self.expect_db_error(
            "ARTIFACT_RIGHTS_EVIDENCE_REQUIRED",
            lambda: self.approve(release, evidence | {"artifact_rights": {}}),
        )
        self.approve(release, evidence)
        self.freeze(release)
        with database.transaction() as admin:
            reasons = admin.execute(
                "SELECT issue_code FROM sources.qa_issue WHERE release_id = %s ORDER BY issue_code",
                (UUID(release["release_id"]),),
            ).fetchall()
        self.assertEqual(
            reasons, [("STREET_SIDE_UNKNOWN",), ("ZONE_GEOMETRY_UNREPRESENTABLE",)]
        )

    def test_rights_scope_and_real_activation_gates(self):
        for variant in ("rights", "scope", "production_like", "unenrolled"):
            with self.subTest(variant=variant):
                scope = f"{self.scope}-{variant}"
                params, lineage = self.candidate(
                    scope=scope, production_like=variant == "production_like"
                )
                release = self.register(params)
                self.fixture_gates(
                    params,
                    lineage,
                    rights=variant != "rights",
                    scope=variant != "scope",
                    enrolled=variant != "unenrolled",
                )
                expected = {
                    "rights": "SOURCE_RIGHTS_NOT_APPROVED",
                    "scope": "PUBLICATION_SCOPE_NOT_APPROVED",
                }.get(variant, "REAL_PUBLICATION_DISABLED")
                self.expect_db_error(
                    expected,
                    lambda: self.approve(release, self.evidence(release, lineage)),
                )
                self.expect_db_error(
                    "PUBLICATION_TARGET_NOT_FROZEN",
                    lambda: self.change(UUID(release["release_id"]), scope=scope),
                )
                self.assertIsNone(self.pointer(scope))

    def test_frozen_payload_and_provenance_reject_normal_sql_mutations(self):
        target = self.frozen(
            zones=[
                curb(
                    1,
                    geometry={
                        "type": "LineString",
                        "coordinates": [[0, 0], [0, 0], [0, 1]],
                    },
                )
            ]
        )

        def mutate(statement):
            with self.user_admin() as admin:
                admin.execute(statement, (target,))

        statements = (
            (
                "UPDATE sources.dataset_release SET approved_by = 'other' WHERE release_id = %s",
                "RELEASE_IMMUTABLE",
            ),
            (
                "DELETE FROM sources.dataset_release WHERE release_id = %s",
                "RELEASE_IMMUTABLE",
            ),
            (
                "UPDATE geo.release_curb_zone SET source_crs = 'other' WHERE release_id = %s",
                "RELEASE_PROJECTION_IMMUTABLE",
            ),
            (
                "DELETE FROM rules.release_zone_policy_link WHERE release_id = %s",
                "RELEASE_PROJECTION_IMMUTABLE",
            ),
            (
                "INSERT INTO rules.release_policy_definition VALUES (%s, 'injected', '{}', 'PASSED')",
                "RELEASE_PROJECTION_IMMUTABLE",
            ),
            (
                "DELETE FROM sources.qa_issue WHERE release_id = %s",
                "RELEASE_PROJECTION_IMMUTABLE",
            ),
            (
                "UPDATE sources.raw_artifact SET content_uri = 'changed' WHERE artifact_id IN (SELECT raw_artifact_id FROM geo.release_curb_zone WHERE release_id = %s)",
                "PUBLICATION_EVIDENCE_IMMUTABLE",
            ),
            (
                "UPDATE sources.import_batch SET validation_report_sha256 = NULL WHERE batch_id IN (SELECT batch_id FROM sources.dataset_release WHERE release_id = %s)",
                "STAGED_BATCH_IMMUTABLE",
            ),
        )
        for statement, message in statements:
            with self.subTest(message=message):
                self.expect_db_error(message, lambda: mutate(statement), "55000")

    def test_append_only_audit_and_ordinary_app_denied(self):
        target = self.frozen()
        event = self.change(target)
        with self.user("app") as connection:
            self.assertGreaterEqual(
                connection.execute(
                    "SELECT max(version_id) FROM public.goose_db_version"
                ).fetchone()[0],
                3,
            )
        for kind, statement in (
            (
                "app",
                "SELECT publication.change_pointer('ignored', NULL, 0, 'WITHDRAW', 'x', 'x')",
            ),
            ("app", "UPDATE sources.active_release SET release_id = NULL"),
            ("app", "INSERT INTO sources.activation_event DEFAULT VALUES"),
            ("operator", "DELETE FROM sources.activation_event"),
            ("operator", "UPDATE sources.active_release SET release_id = NULL"),
            ("operator", "SET ROLE curbos_publication_executor"),
            ("registrar", "UPDATE geo.release_curb_zone SET resource_id = NULL"),
        ):
            with self.subTest(kind=kind, statement=statement):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.user(kind) as connection:
                        connection.execute(statement)
        for statement in (
            "UPDATE sources.activation_event SET reason = 'changed'",
            "DELETE FROM sources.activation_event",
            "TRUNCATE sources.activation_event",
        ):
            with self.assertRaisesRegex(
                psycopg.Error, "PUBLICATION_EVIDENCE_IMMUTABLE"
            ):
                with self.user_admin() as connection:
                    connection.execute(statement)
        for statement in (
            "UPDATE sources.active_release SET release_id = NULL",
            "INSERT INTO sources.activation_event DEFAULT VALUES",
        ):
            with self.assertRaisesRegex(
                psycopg.Error, "PUBLICATION_POINTER_WORKFLOW_REQUIRED"
            ):
                with self.user_admin() as connection:
                    connection.execute(statement)
        self.assertEqual(event["operator_id"], "synthetic_pr04_operator")
        self.assertEqual(self.events(), [(None, target, "ACTIVATE", 1)])

    def user_admin(self):
        return psycopg.connect(
            host="127.0.0.1",
            port=os.environ["CURBOS_CAPTURE_DB_PORT"],
            dbname="curbos",
            user="curbos",
            password=os.environ["POSTGRES_PASSWORD"],
            sslmode="disable",
            connect_timeout=5,
        )

    def test_concurrent_cas_exactly_one_succeeds(self):
        first, second = self.frozen(), self.frozen()
        barrier = threading.Barrier(2)

        def compete(index, target):
            barrier.wait(timeout=10)
            try:
                return self.change(target, request_key=f"{self.scope}-race-{index}")[
                    "to_release_id"
                ]
            except psycopg.errors.SerializationFailure as error:
                self.assertEqual(
                    error.diag.message_primary, "PUBLICATION_VERSION_CONFLICT"
                )
                return None

        with ThreadPoolExecutor(max_workers=2) as workers:
            pending = [
                workers.submit(compete, index, target)
                for index, target in enumerate((first, second))
            ]
            results = [future.result(timeout=20) for future in pending]
        self.assertEqual(results.count(None), 1)
        winner = UUID(next(value for value in results if value is not None))
        self.assertEqual(self.pointer(), (winner, 1))
        self.assertEqual(self.events(), [(None, winner, "ACTIVATE", 1)])

    def test_versions_idempotency_and_rollback_preserve_releases(self):
        first, second, never_active = self.frozen(), self.frozen(), self.frozen()
        original = self.change(first)
        self.expect_db_error(
            "PUBLICATION_VERSION_CONFLICT",
            lambda: self.change(second, request_key=f"{self.scope}-stale"),
            "40001",
        )
        self.expect_db_error(
            "PUBLICATION_IDEMPOTENCY_CONFLICT", lambda: self.change(second), "23505"
        )
        self.expect_db_error(
            "ROLLBACK_TARGET_NEVER_ACTIVE",
            lambda: self.change(never_active, action="ROLLBACK", expected=1),
        )
        self.change(second, expected=1)
        self.assertEqual(self.change(first), original)
        rolled_back = self.change(first, expected=2, action="ROLLBACK")
        self.assertEqual(
            (rolled_back["from_release_id"], rolled_back["pointer_version_after"]),
            (str(second), 3),
        )
        with database.transaction() as admin:
            self.assertEqual(
                admin.execute(
                    "SELECT count(*) FROM geo.release_curb_zone WHERE release_id IN (%s, %s)",
                    (first, second),
                ).fetchone()[0],
                2,
            )
        self.assertEqual(self.pointer(), (first, 3))
        self.assertEqual(
            self.events(),
            [
                (None, first, "ACTIVATE", 1),
                (first, second, "ACTIVATE", 2),
                (second, first, "ROLLBACK", 3),
            ],
        )

    def test_failed_audit_insert_rolls_back_pointer_on_activation_and_withdrawal(self):
        target = self.frozen()
        other = self.frozen()
        self.change(target)
        with self.user_admin() as admin:
            admin.execute("""
                CREATE FUNCTION publication.synthetic_fail_audit() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'SYNTHETIC_AUDIT_FAILURE'; END
                $$;
                CREATE TRIGGER synthetic_fail_audit BEFORE INSERT ON sources.activation_event
                FOR EACH ROW EXECUTE FUNCTION publication.synthetic_fail_audit();
            """)
        try:
            self.expect_db_error(
                "SYNTHETIC_AUDIT_FAILURE", lambda: self.change(other, expected=1)
            )
            self.expect_db_error(
                "SYNTHETIC_AUDIT_FAILURE",
                lambda: self.change(None, expected=1, action="WITHDRAW"),
            )
        finally:
            with self.user_admin() as admin:
                admin.execute(
                    "DROP TRIGGER synthetic_fail_audit ON sources.activation_event"
                )
                admin.execute("DROP FUNCTION publication.synthetic_fail_audit()")
        self.assertEqual(self.pointer(), (target, 1))
        self.assertEqual(self.events(), [(None, target, "ACTIVATE", 1)])

    def test_withdrawal_scope_isolation_and_revoked_rights(self):
        other_scope = f"{self.scope}-other"
        first = self.frozen()
        other = self.frozen(scope=other_scope)
        self.change(first)
        self.change(
            other, scope=other_scope, request_key=f"{self.scope}-other-activate"
        )
        self.expect_db_error(
            "PUBLICATION_TARGET_SCOPE_MISMATCH", lambda: self.change(other, expected=1)
        )
        with self.user_admin() as admin:
            admin.execute(
                "UPDATE sources.source_dataset SET rights_status = 'WITHDRAWN' "
                "WHERE dataset_id::text IN (SELECT lineage->>'dataset_id' FROM publication.release_evidence WHERE release_id = %s)",
                (first,),
            )
        withdrawn = self.change(None, expected=1, action="WITHDRAW")
        self.assertEqual(withdrawn["from_release_id"], str(first))
        self.assertEqual(self.pointer(), (None, 2))
        self.assertEqual(self.pointer(other_scope), (other, 1))
        self.expect_db_error(
            "SOURCE_RIGHTS_NOT_APPROVED", lambda: self.change(first, expected=2)
        )
        with self.user_admin() as admin:
            admin.execute(
                "UPDATE sources.source_dataset SET rights_status = 'APPROVED' "
                "WHERE dataset_id::text IN (SELECT lineage->>'dataset_id' FROM publication.release_evidence WHERE release_id = %s)",
                (first,),
            )
        self.expect_db_error(
            "PUBLICATION_TARGET_WITHDRAWN",
            lambda: self.change(first, expected=2, action="ROLLBACK"),
        )

    def test_restart_keeps_release_pointer_and_audit(self):
        target = self.frozen()
        original = self.change(target)
        subprocess.run(
            ["docker", "restart", os.environ["CURBOS_TEST_DB_CONTAINER"]],
            check=True,
            capture_output=True,
            timeout=30,
        )
        for _ in range(50):
            # Docker may reallocate an ephemeral host port on restart.
            port_result = subprocess.run(
                ["docker", "port", os.environ["CURBOS_TEST_DB_CONTAINER"], "5432/tcp"],
                capture_output=True,
                check=False,
                text=True,
                timeout=3,
            )
            host, _, port = port_result.stdout.strip().rpartition(":")
            if port_result.returncode or host != "127.0.0.1" or not port.isdecimal():
                time.sleep(0.1)
                continue
            os.environ["CURBOS_CAPTURE_DB_PORT"] = port
            try:
                with self.user_admin() as admin:
                    frozen = admin.execute(
                        "SELECT status FROM sources.dataset_release WHERE release_id = %s",
                        (target,),
                    ).fetchone()
                break
            except psycopg.OperationalError:
                time.sleep(0.1)
        else:
            self.fail("Disposable PostgreSQL did not recover after restart")
        self.assertEqual(frozen, ("FROZEN",))
        self.assertEqual(self.pointer(), (target, 1))
        self.assertEqual(self.change(target), original)
        self.assertEqual(self.events(), [(None, target, "ACTIVATE", 1)])
