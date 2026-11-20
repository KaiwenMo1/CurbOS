"""Invented source records for ADR-028 tests. These coordinates do not depict parking."""

import os
import subprocess
from copy import deepcopy
from pathlib import Path
from uuid import UUID

from data.cds_capture import database
from data.cds_capture.__main__ import arguments
from data.cds_capture.manifest import canonical, digest, parse_json


def key(number):
    return str(UUID(int=number))


def zone(number=1, policies=None, geometry=None):
    return {
        "curb_zone_id": key(number),
        "curb_policy_ids": [key(100)] if policies is None else policies,
        "geometry": (
            {"type": "LineString", "coordinates": [[0, 0], [0, 1]]}
            if geometry is None
            else geometry
        ),
    }


def policy(number=100):
    return {
        "curb_policy_id": key(number),
        "rules": [{"activity": "synthetic", "user_classes": []}],
    }


def envelope(role, records, timestamp=1774497600.0):
    return {"data": [{role: records}], "last_updated": timestamp, "license_url": None}


class Bundle:
    def __init__(self, base, *, scope="synthetic-research"):
        self.base = Path(base)
        for name in ("input", "artifact", "staging", "report"):
            path = self.base / name
            path.mkdir(mode=0o700, parents=True)
            setattr(self, name, path)
        self.manifest = {
            "manifest_schema_version": 1,
            "scope_key": scope,
            "publisher_key": "synthetic-test",
            "dataset_key": self.base.name,
            "catalog_uri": "https://synthetic-cds.invalid/catalog",
            "source_profile": "synthetic-cds-json",
            "adapter_version": "1",
            "source_profile_version": "1",
            "declared_captured_at_utc": "2000-01-01T00:00:00Z",
            "rights_status": "UNKNOWN",
            "components": [],
        }
        self.component("zones", envelope("zones", [zone()]))
        self.component("policies", envelope("policies", [policy()]))
        self.save()

    def entry(self, role):
        return next(
            item for item in self.manifest["components"] if item["role"] == role
        )

    def component(self, role, payload):
        self.manifest["components"] = [
            item for item in self.manifest["components"] if item["role"] != role
        ]
        raw = payload if isinstance(payload, bytes) else canonical(payload)
        name = f"{role}.json"
        (self.input / name).write_bytes(raw)
        self.manifest["components"].append(
            {
                "role": role,
                "relative_path": name,
                "sha256": digest(raw),
                "byte_size": len(raw),
                "source_format": "json",
                "original_source_uri": f"https://synthetic-cds.invalid/{role}",
            }
        )

    def save(self):
        (self.input / "manifest.json").write_bytes(canonical(self.manifest))

    def flags(self, *extra):
        return [
            "--manifest",
            "manifest.json",
            "--input-root",
            str(self.input),
            "--artifact-root",
            str(self.artifact),
            "--staging-root",
            str(self.staging),
            "--report-root",
            str(self.report),
            *extra,
        ]

    def args(self, *extra):
        return arguments(self.flags(*extra))

    def relocate(self, base):
        second = Bundle(base)
        second.manifest = deepcopy(self.manifest)
        for entry in second.manifest["components"]:
            path = entry["relative_path"]
            (second.input / path).write_bytes((self.input / path).read_bytes())
        second.save()
        return second

    def staged(self, result, filename="report.json"):
        path = self.staging / result["batch_id"] / filename
        if path.suffix == ".ndjson":
            return [
                parse_json(line, "TEST_FIXTURE_JSON")
                for line in path.read_bytes().splitlines()
            ]
        return parse_json(path.read_bytes(), "TEST_FIXTURE_JSON")


def prepare_disposable_database():
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
            "INSERT INTO sources.publication_scope (scope_key, display_name) VALUES ('synthetic-research', 'Synthetic') ON CONFLICT (scope_key) DO NOTHING"
        )


def offline_command_prefix():
    prefix = ["unshare", "-Urn", "--"]
    probe = subprocess.run([*prefix, "true"], capture_output=True, check=False)
    if probe.returncode and os.environ.get("GITHUB_ACTIONS") == "true":
        return [
            "sudo",
            "-n",
            "--preserve-env=CURBOS_CAPTURE_DB_PORT,PYTHONDONTWRITEBYTECODE",
            "unshare",
            "-n",
            f"--setgid={os.getgid()}",
            f"--setuid={os.getuid()}",
            "--",
        ]
    return prefix
