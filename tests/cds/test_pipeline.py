"""PR-02 acceptance checks against a single disposable PostGIS project."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from psycopg import sql

from data.cds_capture import database
from data.cds_capture.__main__ import run
from data.cds_capture.manifest import CaptureError, canonical, digest, parse_json
from fixtures import Bundle, envelope, key, policy, zone

_PRIVATE = ("source_dataset", "raw_artifact", "import_batch", "import_artifact")
_PUBLIC = (
    "sources.dataset_release",
    "sources.active_release",
    "sources.activation_event",
    "geo.release_curb_zone",
    "geo.parking_resource",
    "geo.source_resource_link",
    "rules.release_policy_definition",
    "rules.release_zone_policy_link",
    "sources.release_area",
    "sources.release_area_zone",
)


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Authorization applies only to the named disposable Compose container.
        project = os.environ["COMPOSE_PROJECT_NAME"]
        container = os.environ["CURBOS_TEST_DB_CONTAINER"]
        port = os.environ["CURBOS_CAPTURE_DB_PORT"]
        if not project.startswith("curbos-db-test-") or len(container) != 64:
            raise RuntimeError("capture tests require an isolated Compose project")
        inspected = subprocess.check_output(
            [
                "docker",
                "inspect",
                "--format",
                '{{index .Config.Labels "com.docker.compose.project"}}/{{index .Config.Labels "com.docker.compose.service"}} '
                '{{range index .NetworkSettings.Ports "5432/tcp"}}{{.HostIp}}:{{.HostPort}}{{end}}',
                container,
            ],
            text=True,
        ).strip()
        if inspected != f"{project}/db 127.0.0.1:{port}":
            raise RuntimeError(
                "capture database target differs from the disposable service"
            )
        if (
            os.environ.get("PGUSER", "curbos") != "curbos"
            or os.environ.get("PGDATABASE", "curbos") != "curbos"
        ):
            raise RuntimeError(
                "capture tests require the disposable Compose role and database"
            )
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO sources.publication_scope (scope_key, display_name) VALUES ('synthetic-research', 'Synthetic')"
            )

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="curbos-cds-db-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.bundle = Bundle(self.base / f"synthetic-{self._testMethodName}")

    def counts(self):
        with database.transaction() as connection:
            return tuple(
                connection.execute(
                    sql.SQL("SELECT count(*) FROM sources.{}").format(
                        sql.Identifier(name)
                    )
                ).fetchone()[0]
                for name in _PRIVATE
            )

    def state(self, batch_id):
        with database.transaction() as connection:
            return connection.execute(
                "SELECT status, validation_report_sha256 FROM sources.import_batch WHERE batch_id = %s",
                (UUID(batch_id),),
            ).fetchone()

    def capture(self, bundle=None):
        result = run((bundle or self.bundle).args())
        self.assertEqual(result["state"], "STAGED", result)
        self.assertFalse(result["public_eligible"])
        return result

    def subprocess(self, snippet=None, bundle=None, prefix=(), extra=(), env=None):
        executable = (
            [sys.executable, "-c", snippet]
            if snippet
            else [sys.executable, "-m", "data.cds_capture"]
        )
        return subprocess.run(
            (*prefix, *executable, *(bundle or self.bundle).flags(*extra)),
            capture_output=True,
            check=False,
            timeout=45,
            env=env,
        )

    def failure(self, code):
        result = run(self.bundle.args())
        self.assertEqual((result["state"], result["code"]), ("FAILED", code), result)
        prefix = "failure-"
        self.assertTrue(result["evidence_report"].startswith(prefix))
        return result

    def test_t01_clean_capture_provenance_and_private_stage(self):
        self.bundle.save()
        previous = self.counts()
        completed = self.subprocess()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = parse_json(completed.stdout, "TEST")
        self.assertEqual(result["state"], "STAGED")
        self.assertFalse(result["public_eligible"])
        self.assertEqual(
            tuple(a - b for a, b in zip(self.counts(), previous)), (1, 2, 1, 2)
        )
        stage_report = self.bundle.staged(result)
        self.assertEqual(stage_report["components"]["zones"]["record_count"], 1)
        self.assertEqual(stage_report["quarantined_count"], 0)
        stage_dir = self.bundle.staging / result["batch_id"]
        self.assertEqual(
            self.state(result["batch_id"]),
            ("STAGED", digest((stage_dir / "report.json").read_bytes())),
        )
        for entry in self.bundle.manifest["components"]:
            retained = self.bundle.artifact / entry["sha256"]
            self.assertEqual(
                retained.read_bytes(),
                (self.bundle.input / entry["relative_path"]).read_bytes(),
            )
            self.assertEqual(retained.stat().st_mode & 0o777, 0o400)
        for filename, expected in stage_report["stage_files"].items():
            raw = (stage_dir / filename).read_bytes()
            self.assertEqual(expected, {"sha256": digest(raw), "byte_size": len(raw)})
        evidence = parse_json(
            (self.bundle.report / result["evidence_report"]).read_bytes(), "TEST"
        )
        self.assertEqual(
            evidence["manifest"]["catalog_uri"], "https://synthetic-cds.invalid/catalog"
        )
        with database.transaction() as connection:
            records = connection.execute(
                """
                SELECT d.catalog_uri, d.rights_status, a.content_uri, a.content_sha256, a.metadata
                FROM sources.raw_artifact a JOIN sources.source_dataset d USING (dataset_id)
                WHERE d.dataset_id = %s
                """,
                (UUID(evidence["dataset_id"]),),
            ).fetchall()
        self.assertEqual(len(records), 2)
        for origin, rights, uri, content_sha, metadata in records:
            self.assertEqual(origin, "https://synthetic-cds.invalid/catalog")
            self.assertEqual(rights, "UNKNOWN")
            self.assertEqual(uri, f"cas+sha256:{content_sha}")
            self.assertTrue(
                metadata["original_source_uri"].startswith(
                    "https://synthetic-cds.invalid/"
                )
            )

    def test_t02_exact_replay_and_version_change(self):
        first = self.capture()
        counts = self.counts()
        self.assertEqual(self.capture(), first)
        self.assertEqual(self.counts(), counts)
        self.bundle.manifest["adapter_version"] = "2"
        self.bundle.save()
        self.assertNotEqual(self.capture()["batch_id"], first["batch_id"])
        self.assertEqual(
            tuple(a - b for a, b in zip(self.counts(), counts)), (0, 0, 1, 2)
        )

    def test_t02_new_bytes_with_updated_manifest_create_new_capture(self):
        first = self.capture()
        counts = self.counts()
        self.bundle.component("zones", envelope("zones", [zone(2)]))
        self.bundle.save()
        changed = self.capture()
        self.assertNotEqual(
            first["capture_manifest_sha256"], changed["capture_manifest_sha256"]
        )
        self.assertEqual(
            tuple(a - b for a, b in zip(self.counts(), counts)), (0, 1, 1, 2)
        )

    def test_t03_path_component_order_and_capture_time_do_not_change_identity(self):
        first = self.capture()
        counts = self.counts()
        old = self.bundle.input / "zones.json"
        old.rename(old.with_name("moved-zones.json"))
        self.bundle.entry("zones")["relative_path"] = "moved-zones.json"
        self.bundle.manifest["components"].reverse()
        self.bundle.manifest["declared_captured_at_utc"] = "2001-01-01T00:00:00Z"
        self.bundle.save()
        second = self.capture()
        self.assertEqual(first["batch_id"], second["batch_id"])
        self.assertEqual(
            first["capture_manifest_sha256"], second["capture_manifest_sha256"]
        )
        self.assertNotEqual(first["evidence_report"], second["evidence_report"])
        self.assertEqual(self.counts(), counts)
        published_local = parse_json(
            (self.bundle.report / second["evidence_report"]).read_bytes(), "TEST"
        )
        self.assertEqual(
            published_local["manifest"]["components"][0]["relative_path"],
            "moved-zones.json",
        )

    def test_t04_t07_preflight_failures_leave_db_untouched(self):
        counts = self.counts()
        path = self.bundle.input / "zones.json"
        original = path.read_bytes()
        path.write_bytes(b"x" * len(original))
        self.failure("COMPONENT_DIGEST_MISMATCH")
        path.write_bytes(original)
        self.bundle.component("zones", b"{")
        self.bundle.save()
        self.failure("INVALID_COMPONENT_JSON")
        self.bundle.manifest["scope_key"] = "unknown-synthetic-scope"
        self.bundle.component("zones", envelope("zones", [zone()]))
        self.bundle.save()
        self.failure("IMPORT_SCOPE_NOT_FOUND")
        self.assertEqual(self.counts(), counts)

    def test_t08_duplicates_and_invalid_ids_are_quarantined(self):
        invalid = zone() | {"curb_zone_id": "not-a-uuid"}
        rows = [zone(), zone(), invalid, None]
        self.bundle.component("zones", envelope("zones", rows))
        self.bundle.save()
        result = self.capture()
        report = self.bundle.staged(result)["components"]["zones"]
        self.assertEqual(
            (report["duplicate_id_count"], report["duplicate_id_record_count"]), (1, 2)
        )
        staged = self.bundle.staged(result, "zones.ndjson")
        self.assertEqual([row["payload"] for row in staged], rows)
        self.assertEqual([row["source_index"] for row in staged], [0, 1, 2, 3])
        quarantine = self.bundle.staged(result, "quarantine.ndjson")
        self.assertEqual(len(quarantine), 4)
        self.assertIn("SOURCE_ID_INVALID", quarantine[2]["issues"])

    def test_t09_missing_ref_counts_and_ambiguous_policy(self):
        missing = key(200)
        self.bundle.component(
            "zones",
            envelope(
                "zones",
                [
                    zone(1, [key(100), missing, missing]),
                    zone(2, [missing]),
                    zone(3, [key(100)]),
                ],
            ),
        )
        self.bundle.component("policies", envelope("policies", [policy(), policy()]))
        self.bundle.save()
        result = self.capture()
        report = self.bundle.staged(result)
        self.assertEqual(report["missing_policy_ref_count"], 3)
        self.assertEqual(report["zones_with_missing_policy_refs"], 2)
        self.assertEqual(
            [item["source_zone_id"] for item in report["missing_policy_refs"]],
            [key(1), key(1), key(2)],
        )
        self.assertEqual(
            [item["source_position"] for item in report["missing_policy_refs"]],
            [1, 2, 0],
        )
        records = self.bundle.staged(result, "zones.ndjson")
        self.assertTrue(
            all(record["policy_ref_status"] == "INCOMPLETE" for record in records)
        )
        self.assertIn("POLICY_REFERENCE_AMBIGUOUS", records[2]["issues"])
        self.assertFalse(report["public_eligible"])

    def test_t10_unsupported_policy_shapes_keep_raw_values(self):
        mixed = policy(101)
        mixed["rules"].append(
            {"activity": "synthetic", "user_classes": "unsupported scalar"}
        )
        unsupported = policy(102) | {"rules": {"unrecognized": True}}
        self.bundle.component(
            "policies", envelope("policies", [policy(), mixed, unsupported])
        )
        self.bundle.save()
        result = self.capture()
        rows = self.bundle.staged(result, "policies.ndjson")
        self.assertEqual(
            [row["payload"] for row in rows], [policy(), mixed, unsupported]
        )
        self.assertEqual(
            [row["status"] for row in rows], ["PARSED", "QUARANTINED", "QUARANTINED"]
        )
        self.assertEqual(
            self.bundle.staged(result)["components"]["policies"]["issue_counts"],
            {"UNSUPPORTED_POLICY_FORM": 2},
        )

    def test_t11_geometry_issues_and_precise_original_coordinates(self):
        geometries = [
            {"type": "LineString", "coordinates": [[181, 0], [0, 1]]},
            {"type": "Point", "coordinates": [0, 0]},
            {"type": "LineString", "coordinates": []},
            {"type": "LineString", "coordinates": [[0, 0], [0, 0], [0, 1]]},
            {"type": "LineString", "coordinates": [[0, 0], [0, 0]]},
            {"type": "LineString", "coordinates": [[0, 0], [0, 1]]},
        ]
        raw = canonical(
            envelope(
                "zones",
                [
                    zone(i + 1, geometry=geometry)
                    for i, geometry in enumerate(geometries)
                ],
            )
        )
        raw = raw.replace(b"[[0,0],[0,1]]", b"[[0.123456789123456789,0],[0,1]]")
        self.bundle.component("zones", raw)
        self.bundle.save()
        result = self.capture()
        rows = self.bundle.staged(result, "zones.ndjson")
        for index, code in enumerate(
            (
                "ZONE_GEOMETRY_INVALID_COORDINATES",
                "ZONE_GEOMETRY_NOT_LINESTRING",
                "ZONE_GEOMETRY_EMPTY",
                "ZONE_GEOMETRY_REPEATED_VERTEX",
                "ZONE_GEOMETRY_DEGENERATE",
            )
        ):
            self.assertIn(code, rows[index]["issues"])
        self.assertEqual(rows[5]["status"], "PARSED")
        self.assertIn(b"0.123456789123456789", canonical(rows[5]))
        self.assertEqual(rows[5]["geometry_evidence"], "SOURCE_REPORTED")
        self.assertEqual(
            rows[5]["source_geometry_sha256"],
            digest(canonical(rows[5]["payload"]["geometry"])),
        )

    def test_t12_optional_areas_and_source_geometry_are_not_coverage(self):
        absent = self.capture()
        self.assertTrue(self.bundle.staged(absent)["areas_not_included"])
        self.assertFalse(
            (self.bundle.staging / absent["batch_id"] / "areas.ndjson").exists()
        )
        areas = [
            {"curb_area_id": key(301)},
            {
                "curb_area_id": key(302),
                "geometry": {
                    "type": "MultiLineString",
                    "coordinates": [[[0, 0], [0, 1]]],
                },
            },
        ]
        self.bundle.component("areas", envelope("areas", areas))
        self.bundle.save()
        present = self.capture()
        self.assertNotEqual(absent["batch_id"], present["batch_id"])
        self.assertFalse(self.bundle.staged(present)["areas_not_included"])
        rows = self.bundle.staged(present, "areas.ndjson")
        self.assertEqual([row["payload"] for row in rows], areas)
        self.assertEqual(
            [row["issues"] for row in rows],
            [["AREA_GEOMETRY_MISSING"], ["AREA_GEOMETRY_MULTILINESTRING"]],
        )

    def test_t14_database_failure_before_commit_rolls_back_every_row(self):
        counts = self.counts()
        original = database.register

        def abort(*args):
            original(*args)
            raise CaptureError("TEST_ABORT_BEFORE_COMMIT")

        with patch.object(database, "register", side_effect=abort):
            self.failure("TEST_ABORT_BEFORE_COMMIT")
        self.assertEqual(self.counts(), counts)
        self.assertEqual(
            len(
                [
                    entry
                    for entry in self.bundle.artifact.iterdir()
                    if not entry.name.startswith(".")
                ]
            ),
            2,
        )
        self.capture()

    def test_t15_crash_after_registration_reuses_batch(self):
        completed = self.subprocess(
            "import os; from data.cds_capture import __main__ as cli; "
            "cli.stage.complete_stage = lambda *args: os._exit(93); cli.main()"
        )
        self.assertEqual(completed.returncode, 93, completed.stderr)
        batch_id = (
            next(self.bundle.staging.glob(".*.lock"))
            .name.removeprefix(".")
            .removesuffix(".lock")
        )
        self.assertEqual(self.state(batch_id), ("CAPTURED", None))
        self.assertFalse((self.bundle.staging / batch_id).exists())
        counts = self.counts()
        self.assertEqual(self.capture()["batch_id"], batch_id)
        self.assertEqual(self.counts(), counts)

    def test_t16_concurrent_registrations_in_independent_stores(self):
        second = self.bundle.relocate(self.base / "other-store")
        counts = self.counts()
        gate = self.base / "start-gate"
        gate.mkdir()
        env = os.environ | {"CURBOS_CDS_TEST_GATE": str(gate)}
        synchronize = """
import os
import time
from pathlib import Path
from data.cds_capture import __main__ as cli

gate = Path(os.environ["CURBOS_CDS_TEST_GATE"])
original = cli.database.register

def synchronized_register(*args):
    (gate / str(os.getpid())).touch()
    deadline = time.monotonic() + 10
    while len(list(gate.iterdir())) < 2:
        if time.monotonic() > deadline:
            raise RuntimeError("concurrent capture did not reach registration")
        time.sleep(0.001)
    return original(*args)

cli.database.register = synchronized_register
raise SystemExit(cli.main())
"""
        with (
            subprocess.Popen(
                [sys.executable, "-c", synchronize, *self.bundle.flags()],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            ) as first,
            subprocess.Popen(
                [sys.executable, "-c", synchronize, *second.flags()],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            ) as concurrent,
        ):
            results = []
            for child in (first, concurrent):
                try:
                    stdout, stderr = child.communicate(timeout=45)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.communicate()
                    raise
                self.assertEqual(child.returncode, 0, stderr)
                results.append(parse_json(stdout, "TEST"))
        self.assertEqual(results[0], results[1])
        self.assertEqual(
            tuple(a - b for a, b in zip(self.counts(), counts)), (1, 2, 1, 2)
        )
        first_report = self.bundle.staged(results[0])
        self.assertEqual(second.staged(results[1]), first_report)

    def test_t16_shared_store_concurrent_retry(self):
        counts = self.counts()
        command = [sys.executable, "-m", "data.cds_capture", *self.bundle.flags()]
        with (
            subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            ) as first,
            subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            ) as second,
        ):
            outputs = []
            try:
                for child in (first, second):
                    stdout, stderr = child.communicate(timeout=45)
                    self.assertEqual(child.returncode, 0, stderr)
                    outputs.append(parse_json(stdout, "TEST"))
            finally:
                for child in (first, second):
                    if child.poll() is None:
                        child.kill()
                        child.communicate()
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(
            tuple(a - b for a, b in zip(self.counts(), counts)), (1, 2, 1, 2)
        )
        self.assertFalse(list(self.bundle.artifact.glob("*.partial")))
        self.assertFalse(list(self.bundle.staging.glob("*.partial")))

    def test_t18_retained_corruption_is_detected_and_untouched(self):
        self.capture()
        counts = self.counts()
        path = self.bundle.artifact / self.bundle.entry("zones")["sha256"]
        path.chmod(0o600)
        path.write_bytes(b"corrupt synthetic artifact")
        path.chmod(0o400)
        self.failure("RETAINED_FILE_MISMATCH")
        self.assertEqual(path.read_bytes(), b"corrupt synthetic artifact")
        self.assertEqual(self.counts(), counts)

    def test_t19_full_pipeline_with_network_namespace_and_unix_socket(self):
        env = os.environ | {"CURBOS_CAPTURE_DB_PORT": "5432"}
        socket_dir = os.environ["CURBOS_TEST_DB_SOCKET"]
        prefix = ["unshare", "-Urn", "--"]
        probe = subprocess.run([*prefix, "true"], capture_output=True, check=False)
        if probe.returncode and os.environ.get("GITHUB_ACTIONS") == "true":
            prefix = [
                "sudo",
                "-n",
                "--preserve-env=CURBOS_CAPTURE_DB_PORT,PYTHONDONTWRITEBYTECODE",
                "unshare",
                "-n",
                f"--setgid={os.getgid()}",
                f"--setuid={os.getuid()}",
                "--",
            ]
        code = (
            "import socket; from data.cds_capture import __main__ as cli; "
            "probe = socket.socket(); probe.settimeout(1); "
            "assert probe.connect_ex(('127.0.0.1', 5432)) != 0; probe.close(); "
            "raise SystemExit(cli.main())"
        )
        completed = self.subprocess(
            code, prefix=prefix, extra=("--db-socket-dir", socket_dir), env=env
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(parse_json(completed.stdout, "TEST")["state"], "STAGED")

    def test_t19_rejects_ambient_libpq_service_routing(self):
        counts = self.counts()
        with patch.dict(os.environ, {"PGSERVICE": "synthetic-ambient-service"}):
            self.failure("AMBIENT_DATABASE_ROUTING_NOT_ALLOWED")
        self.assertEqual(self.counts(), counts)

    def test_t20_public_projection_tables_are_untouched(self):
        def contents():
            with database.transaction() as connection:
                return {
                    table: connection.execute(
                        sql.SQL(
                            "SELECT to_jsonb(row) FROM {} AS row ORDER BY to_jsonb(row)::text"
                        ).format(sql.Identifier(*table.split(".")))
                    ).fetchall()
                    for table in _PUBLIC
                }

        before = contents()
        self.capture()
        self.assertEqual(contents(), before)

    def test_t21_crash_recovery_cleans_only_private_scratch(self):
        interrupted = self.subprocess(
            "import os; from data.cds_capture import __main__ as cli; original = cli.files.write_file; "
            "cli.files.write_file = lambda parent, name, chunks: "
            "(original(parent, name, chunks), os._exit(94) if name == 'zones.ndjson' else None)[0]; "
            "cli.main()"
        )
        self.assertEqual(interrupted.returncode, 94, interrupted.stderr)
        partial = next(self.bundle.staging.glob(".*.partial"))
        batch = partial.name.removeprefix(".").removesuffix(".partial")
        self.assertEqual(self.state(batch), ("CAPTURED", None))
        raw_partial = (
            self.bundle.artifact / f".{self.bundle.entry('zones')['sha256']}.partial"
        )
        raw_partial.write_bytes(b"interrupted synthetic write")
        counts = self.counts()
        result = self.capture()
        self.assertEqual(result["batch_id"], batch)
        self.assertFalse(partial.exists())
        self.assertFalse(raw_partial.exists())
        self.assertEqual(self.counts(), counts)
        self.assertEqual(result, self.capture())

    def test_t21_crash_after_atomic_promotion_revalidates_stage(self):
        interrupted = self.subprocess(
            "import os; from data.cds_capture import __main__ as cli; "
            "cli.database.mark_staged = lambda *args: os._exit(95); cli.main()"
        )
        self.assertEqual(interrupted.returncode, 95, interrupted.stderr)
        directory = next(
            item for item in self.bundle.staging.iterdir() if item.is_dir()
        )
        self.assertEqual(self.state(directory.name), ("CAPTURED", None))
        report = directory / "report.json"
        before = report.read_bytes()
        report.chmod(0o600)
        report.write_bytes(before + b"corrupted")
        report.chmod(0o400)
        self.failure("STAGE_FILE_MISMATCH")
        self.assertEqual(self.state(directory.name), ("CAPTURED", None))
        report.chmod(0o600)
        report.write_bytes(before)
        report.chmod(0o400)
        self.assertEqual(self.capture()["batch_id"], directory.name)
        self.assertEqual(report.read_bytes(), before)
