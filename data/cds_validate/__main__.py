"""Validate one registered CDS stage and prepare an offline candidate package."""

import argparse
import os
import re
import sys
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from data.cds_capture import database, files
from data.cds_capture.manifest import CaptureError, canonical, digest

from .integrity import load_stage, registered_lineage
from .quality import assess

_REPO = Path(__file__).resolve().parents[2]
_VERSION = 1


def _path_pair(stage_dir, output_root):
    stage_dir, output_root = files.absolute(stage_dir), files.absolute(output_root)
    if output_root.is_relative_to(_REPO) or _REPO.is_relative_to(output_root):
        raise CaptureError("OUTPUT_INSIDE_GIT")
    if stage_dir.is_relative_to(output_root) or output_root.is_relative_to(stage_dir):
        raise CaptureError("OVERLAPPING_VALIDATION_PATHS")
    return stage_dir, output_root


def _evidence_rows(records, lineage, candidate_id):
    for role, group in records.items():
        artifact = lineage["artifacts"][role]
        for item in group:
            evidence = {
                "batch_id": lineage["batch_id"],
                "candidate_id": candidate_id,
                "artifact_id": artifact["artifact_id"],
                "source_id": item.key,
                "disposition": item.disposition,
                "reason_codes": sorted(item.reasons),
                "stage_record": item.row,
            }
            if role == "zones":
                evidence["curb_placement"] = "UNVERIFIED"
            yield evidence


def _package_files(
    parent, lineage, candidate_id, records, candidate, summary, existing
):
    written = {}

    def emit(name, chunks):
        if not existing:
            return files.write_file(parent, name, chunks)

        hasher = sha256()
        size = 0
        for chunk in chunks:
            hasher.update(chunk)
            size += len(chunk)
        expected = hasher.hexdigest(), size
        if (
            not files.present(parent, name)
            or files.fingerprint(parent, name) != expected
        ):
            raise CaptureError("CANDIDATE_FILE_MISMATCH")
        return expected

    def record(name, chunks):
        checksum, size = emit(name, chunks)
        written[name] = {"sha256": checksum, "byte_size": size}

    header = {
        "validation_schema_version": _VERSION,
        "candidate_id": candidate_id,
        "candidate_status": "PREPARED_PRIVATE",
        "public_eligible": False,
        "lineage": lineage,
    }
    record(
        "evidence.ndjson",
        map(canonical, _evidence_rows(records, lineage, candidate_id)),
    )
    record(
        "quarantine.ndjson",
        (
            canonical(
                {
                    "batch_id": row["batch_id"],
                    "candidate_id": candidate_id,
                    "artifact_id": row["artifact_id"],
                    "role": row["stage_record"]["role"],
                    "source_index": row["stage_record"]["source_index"],
                    "source_id": row["source_id"],
                    "disposition": row["disposition"],
                    "reason_codes": row["reason_codes"],
                }
            )
            for row in _evidence_rows(records, lineage, candidate_id)
            if row["disposition"] != "ACCEPTED"
        ),
    )
    record("candidate.json", (canonical(header | candidate),))
    record(
        "report.json",
        (canonical(header | summary | {"output_files": written.copy()}),),
    )
    emit(
        "SHA256SUMS",
        (
            f"{descriptor['sha256']}  {name}\n".encode("ascii")
            for name, descriptor in sorted(written.items())
        ),
    )
    if set(os.listdir(parent)) != set(written) | {"SHA256SUMS"}:
        raise CaptureError("CANDIDATE_FILE_SET_MISMATCH")
    os.fsync(parent)
    return written["report.json"]["sha256"]


def _complete_package(output, lineage, candidate_id, records, candidate, summary):
    temporary = f".{candidate_id}.partial"
    with files.lock(output, f".{candidate_id}.lock"):
        files.remove_stage_temporary(output, temporary)
        if files.present(output, candidate_id):
            with files.directory(output, (candidate_id,)) as parent:
                return _package_files(
                    parent, lineage, candidate_id, records, candidate, summary, True
                )

        os.mkdir(temporary, 0o700, dir_fd=output)
        try:
            with files.directory(output, (temporary,)) as parent:
                report_sha = _package_files(
                    parent, lineage, candidate_id, records, candidate, summary, False
                )
            files.promote(output, temporary, candidate_id)
            return report_sha
        finally:
            files.remove_stage_temporary(output, temporary)


def prepare(connection, batch_id, scope_key, staged):
    if not isinstance(batch_id, UUID):
        raise CaptureError("INVALID_BATCH_ID")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", scope_key):
        raise CaptureError("INVALID_SCOPE_KEY")
    lineage = registered_lineage(connection, batch_id, scope_key)
    stage_report, rows = load_stage(staged, lineage)
    for role, artifact in lineage["artifacts"].items():
        artifact["declared_source_crs"] = stage_report["components"][role]["source_crs"]
    postgis, geos = connection.execute(
        "SELECT public.postgis_lib_version(), public.postgis_geos_version()"
    ).fetchone()
    lineage["geometry_engine"] = {"postgis": postgis, "geos": geos}
    records, candidate, summary = assess(connection, stage_report, rows)
    key = digest(canonical(lineage))
    candidate_id = str(uuid5(NAMESPACE_URL, f"curbos:cds-validation:v{_VERSION}:{key}"))
    return lineage, candidate_id, records, candidate, summary


def run(batch_id, scope_key, stage_dir, output_root, *, db_socket_dir=None):
    stage_dir, output_root = _path_pair(stage_dir, output_root)
    with (
        files.root(stage_dir, private=True) as staged,
        files.root(output_root, private=True) as output,
    ):
        if os.path.samestat(os.fstat(staged), os.fstat(output)):
            raise CaptureError("OVERLAPPING_VALIDATION_PATHS")
        with database.transaction(db_socket_dir) as connection:
            connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            lineage, candidate_id, records, candidate, summary = prepare(
                connection, batch_id, scope_key, staged
            )
        report_sha = _complete_package(
            output, lineage, candidate_id, records, candidate, summary
        )
    return {
        "state": "VALIDATION_COMPLETE",
        "batch_id": str(batch_id),
        "candidate_id": candidate_id,
        "report_sha256": report_sha,
        "public_eligible": False,
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
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--db-socket-dir", type=Path)
    args = parser.parse_args()
    try:
        result = run(**vars(args))
    except (CaptureError, OSError) as error:
        failure = {
            "state": "FAILED",
            "code": error.code
            if isinstance(error, CaptureError)
            else "VALIDATION_FILESYSTEM_FAILURE",
        }
        if isinstance(error, CaptureError) and error.role is not None:
            failure["role"] = error.role
        sys.stderr.write(canonical(failure).decode("ascii"))
        return 1
    sys.stdout.write(canonical(result).decode("ascii"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
