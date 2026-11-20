"""Register private provenance in PostgreSQL using the PR-01 tables."""

import os
import re
from contextlib import contextmanager
from uuid import uuid4

import psycopg

from .manifest import CaptureError, canonical


@contextmanager
def transaction(socket_directory=None):
    port = os.environ.get("CURBOS_CAPTURE_DB_PORT", "")
    if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535:
        raise CaptureError("LOCAL_DATABASE_PORT_REQUIRED")
    if os.environ.get("PGSERVICE") or os.environ.get("PGHOSTADDR"):
        raise CaptureError("AMBIENT_DATABASE_ROUTING_NOT_ALLOWED")
    if socket_directory is not None:
        if (
            not socket_directory.is_absolute()
            or ".." in socket_directory.parts
            or "," in str(socket_directory)
            or any(ord(char) < 32 for char in str(socket_directory))
        ):
            raise CaptureError("INVALID_DATABASE_SOCKET_DIRECTORY")
    host = str(socket_directory) if socket_directory else "127.0.0.1"
    try:
        with psycopg.connect(
            host=host,
            hostaddr="" if socket_directory else host,
            port=port,
            user=os.environ.get("PGUSER", "curbos"),
            dbname=os.environ.get("PGDATABASE", "curbos"),
            password=os.environ.get("PGPASSWORD", ""),
            sslmode="disable",
            gssencmode="disable",
            target_session_attrs="any",
            connect_timeout=5,
            passfile="/dev/null",
            options="-c statement_timeout=30000 -c lock_timeout=10000",
        ) as connection:
            yield connection
    except psycopg.Error:
        # Driver errors may contain credentials, paths or arbitrary server data.
        raise CaptureError("DATABASE_TRANSACTION_FAILED") from None


def _dataset(connection, manifest):
    pair = (manifest["publisher_key"], manifest["dataset_key"])
    connection.execute(
        """
        INSERT INTO sources.source_dataset
          (dataset_id, publisher_key, dataset_key, catalog_uri, source_profile, rights_status, rights_reference)
        VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (publisher_key, dataset_key) DO NOTHING
        """,
        (
            uuid4(),
            *pair,
            manifest["catalog_uri"],
            manifest["source_profile"],
            manifest["rights_status"],
            manifest.get("rights_reference"),
        ),
    )
    return connection.execute(
        "SELECT dataset_id FROM sources.source_dataset WHERE publisher_key = %s AND dataset_key = %s",
        pair,
    ).fetchone()[0]


def _artifact(connection, dataset_id, manifest, snapshot):
    entry = snapshot.entry
    artifact_uri = f"cas+sha256:{entry['sha256']}"
    metadata = {
        "original_source_uri": entry["original_source_uri"],
        "source_timestamp": snapshot.timestamp,
        "declared_rights_status": manifest["rights_status"],
        "declared_rights_reference": manifest.get("rights_reference"),
    }
    connection.execute(
        """
        INSERT INTO sources.raw_artifact
          (artifact_id, dataset_id, component_role, content_uri, content_sha256, byte_size,
           retrieved_at, source_as_of, source_format, source_crs, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (dataset_id, content_sha256) DO NOTHING
        """,
        (
            uuid4(),
            dataset_id,
            entry["role"],
            artifact_uri,
            entry["sha256"],
            entry["byte_size"],
            manifest["declared_captured_at_utc"],
            entry.get("source_as_of"),
            entry["source_format"],
            entry.get("source_crs"),
            canonical(metadata).decode("ascii"),
        ),
    )
    artifact_id, stored_size, stored_uri = connection.execute(
        """
        SELECT artifact_id, byte_size, content_uri FROM sources.raw_artifact
        WHERE dataset_id = %s AND content_sha256 = %s
        """,
        (dataset_id, entry["sha256"]),
    ).fetchone()
    if (stored_size, stored_uri) != (entry["byte_size"], artifact_uri):
        raise CaptureError("REGISTERED_ARTIFACT_CONFLICT", entry["role"])
    return artifact_id


def register(connection, manifest, snapshots, batch_id, capture_digest):
    scope = manifest["scope_key"]
    if (
        scope is not None
        and connection.execute(
            "SELECT 1 FROM sources.publication_scope WHERE scope_key = %s", (scope,)
        ).fetchone()
        is None
    ):
        raise CaptureError("IMPORT_SCOPE_NOT_FOUND")

    metadata = (
        capture_digest,
        scope,
        manifest["adapter_version"],
        manifest["source_profile_version"],
    )
    # PR-01 provides both a batch PK and a unique batch/scope key.
    # Either can arbitrate a concurrent insert. The locked row is checked below.
    inserted = (
        connection.execute(
            """
        INSERT INTO sources.import_batch
          (batch_id, capture_manifest_sha256, scope_key, adapter_version, source_profile_version)
        VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING batch_id
        """,
            (batch_id, *metadata),
        ).fetchone()
        is not None
    )
    # The batch's deterministic UUID and existing PK serialize concurrent registration.
    row = connection.execute(
        """
        SELECT capture_manifest_sha256, scope_key, adapter_version, source_profile_version
        FROM sources.import_batch WHERE batch_id = %s FOR UPDATE
        """,
        (batch_id,),
    ).fetchone()
    if row != metadata:
        raise CaptureError("CAPTURE_BATCH_IDENTITY_CONFLICT")

    dataset_id = _dataset(connection, manifest)
    expected = set()
    for role, snapshot in sorted(snapshots.items()):
        artifact_id = _artifact(connection, dataset_id, manifest, snapshot)
        expected.add((role, artifact_id))
        if inserted:
            connection.execute(
                "INSERT INTO sources.import_artifact (batch_id, component_role, artifact_id) VALUES (%s, %s, %s)",
                (batch_id, role, artifact_id),
            )
    actual = connection.execute(
        "SELECT component_role, artifact_id FROM sources.import_artifact WHERE batch_id = %s",
        (batch_id,),
    ).fetchall()
    if set(actual) != expected:
        raise CaptureError("REGISTERED_COMPONENTS_CONFLICT")
    return {
        "dataset_id": str(dataset_id),
        "artifact_ids": {role: str(key) for role, key in expected},
    }


def mark_staged(connection, batch_id, report_sha):
    result = connection.execute(
        """
        UPDATE sources.import_batch SET status = 'STAGED', validation_report_sha256 = %s
        WHERE batch_id = %s AND status = 'CAPTURED' AND validation_report_sha256 IS NULL
        """,
        (report_sha, batch_id),
    )
    if result.rowcount == 1:
        return
    row = connection.execute(
        "SELECT status, validation_report_sha256 FROM sources.import_batch WHERE batch_id = %s",
        (batch_id,),
    ).fetchone()
    if row != ("STAGED", report_sha):
        raise CaptureError("CAPTURE_STATUS_CONFLICT")
