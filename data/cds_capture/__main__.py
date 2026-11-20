"""Offline CLI for manifest-driven CDS capture and private staging."""

import argparse
import sys
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

from . import database, files, stage
from .manifest import (
    CaptureError,
    canonical,
    digest,
    identity,
    load_manifest,
    verify_inventory,
)

_REPO = Path(__file__).resolve().parents[2]
_MANIFEST_LIMIT = 128 * 1024


def _argument_file(path, input_root):
    if path.is_absolute():
        try:
            path = path.relative_to(input_root)
        except ValueError:
            raise CaptureError("UNSAFE_INPUT_PATH") from None
    return str(path)


def _roots(args):
    discovered = {
        name: files.absolute(getattr(args, f"{name}_root"))
        for name in ("input", "artifact", "staging", "report")
    }
    for name, path in discovered.items():
        if name != "input" and (
            path.is_relative_to(_REPO) or _REPO.is_relative_to(path)
        ):
            raise CaptureError("OUTPUT_INSIDE_GIT")
        if any(
            other != name
            and (path.is_relative_to(candidate) or candidate.is_relative_to(path))
            for other, candidate in discovered.items()
        ):
            raise CaptureError("OVERLAPPING_ROOTS")
    return discovered


def _report(parent, content, failure=False):
    encoded = canonical(content)
    key = uuid4().hex if failure else digest(encoded)
    name = f"{'failure' if failure else 'evidence'}-{key}.json"
    with files.lock(parent, f".{name}.lock"):
        files.retain(parent, name, encoded, (digest(encoded), len(encoded)))
    return name


def _run_capture(args, roots, report_dir, progress):
    with files.root(roots["input"]) as input_dir:
        manifest_raw = files.read_input(
            input_dir,
            _argument_file(args.manifest, roots["input"]),
            limit=_MANIFEST_LIMIT,
        )
        if len(manifest_raw) > _MANIFEST_LIMIT:
            raise CaptureError("MANIFEST_TOO_LARGE")
        manifest = load_manifest(manifest_raw)
        capture_digest, batch_id = identity(manifest)
        progress["capture_manifest_sha256"] = capture_digest
        if args.archive_inventory:
            raw = files.read_input(
                input_dir,
                _argument_file(args.archive_inventory, roots["input"]),
                limit=_MANIFEST_LIMIT,
            )
            if len(raw) > _MANIFEST_LIMIT:
                raise CaptureError("INVENTORY_TOO_LARGE")
            verify_inventory(raw, manifest)

        snapshots = {}
        for entry in manifest["components"]:
            try:
                raw = files.read_input(
                    input_dir, entry["relative_path"], limit=entry["byte_size"]
                )
            except CaptureError as error:
                raise CaptureError(error.code, entry["role"]) from None
            snapshots[entry["role"]] = stage.load_snapshot(entry, raw)

    evidence = {
        "capture_manifest_sha256": capture_digest,
        "manifest": manifest,
        "component_timestamps": {
            role: item.timestamp for role, item in snapshots.items()
        },
        "public_eligible": False,
    }
    result = {"capture_manifest_sha256": capture_digest, "public_eligible": False}
    if args.dry_run:
        filename = _report(report_dir, evidence | {"state": "PREFLIGHT_VERIFIED"})
        return result | {"state": "PREFLIGHT_VERIFIED", "evidence_report": filename}

    with (
        files.root(roots["artifact"], private=True) as artifacts,
        files.root(roots["staging"], private=True) as staging,
        files.lock(staging, f".{batch_id}.lock"),
    ):
        progress["phase"] = "RETAIN_RAW"
        for snapshot in snapshots.values():
            entry = snapshot.entry
            sha = entry["sha256"]
            with files.lock(artifacts, f".{sha}.lock"):
                files.retain(artifacts, sha, snapshot.raw, (sha, entry["byte_size"]))

        progress["phase"] = "REGISTER_PROVENANCE"
        with database.transaction(args.db_socket_dir) as connection:
            registered = database.register(
                connection, manifest, snapshots, batch_id, capture_digest
            )
        progress.update({"phase": "STAGE", "registered_batch_id": str(batch_id)})
        report_sha = stage.complete_stage(staging, snapshots, batch_id, capture_digest)
        report_name = _report(
            report_dir,
            evidence
            | registered
            | {
                "state": "PRIVATE_STAGE_COMPLETE",
                "batch_id": str(batch_id),
                "stage_report_sha256": report_sha,
            },
        )

        progress["phase"] = "RECORD_STAGE_STATUS"
        with database.transaction(args.db_socket_dir) as connection:
            database.mark_staged(connection, batch_id, report_sha)
    return result | {
        "state": "STAGED",
        "batch_id": str(batch_id),
        "evidence_report": report_name,
    }


def _safe_error(error):
    if isinstance(error, CaptureError):
        return {"code": error.code, "role": error.role}
    return {"code": "LOCAL_FILESYSTEM_FAILURE"}


def run(args):
    progress = {"phase": "PREFLIGHT"}
    try:
        roots = _roots(args)
        with ExitStack() as stack:
            report_dir = stack.enter_context(files.root(roots["report"], private=True))
            try:
                return _run_capture(args, roots, report_dir, progress)
            except (CaptureError, OSError) as error:
                failure = (
                    progress
                    | _safe_error(error)
                    | {"state": "FAILED", "public_eligible": False}
                )
                try:
                    filename = _report(report_dir, failure, failure=True)
                except (CaptureError, OSError):
                    return failure | {"evidence_report": None}
                return failure | {"evidence_report": filename}
    except (CaptureError, OSError) as error:
        return _safe_error(error) | {
            "state": "FAILED",
            "public_eligible": False,
            "evidence_report": None,
        }


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse errors may quote user-provided paths or unknown arguments.
        self.print_usage(sys.stderr)
        self.exit(2, '{"code":"INVALID_ARGUMENTS","state":"FAILED"}\n')


def arguments(argv=None):
    parser = _ArgumentParser(description=__doc__)
    for flag in (
        "manifest",
        "input-root",
        "artifact-root",
        "staging-root",
        "report-root",
    ):
        parser.add_argument(f"--{flag}", required=True, type=Path)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="verify local bytes without retaining or registering them",
    )
    parser.add_argument(
        "--archive-inventory",
        type=Path,
        help="opt-in dry-run check of an approved inventory within the input root",
    )
    parser.add_argument(
        "--db-socket-dir", type=Path, help="use a local PostgreSQL Unix socket"
    )
    args = parser.parse_args(argv)
    if args.archive_inventory and not args.dry_run:
        parser.error("--archive-inventory requires --dry-run")
    return args


def main():
    result = run(arguments())
    failed = result["state"] == "FAILED"
    output = sys.stderr if failed else sys.stdout
    output.write(canonical(result).decode("ascii"))
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
