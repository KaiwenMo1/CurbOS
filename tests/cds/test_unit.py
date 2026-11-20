"""Synthetic preflight and parser tests."""

import os
import tempfile
import unittest
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from data.cds_capture import database, files, stage
from data.cds_capture.__main__ import run
from data.cds_capture.manifest import canonical, identity, load_manifest, parse_json
from fixtures import Bundle, envelope, policy


class Preflight(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="curbos-cds-unit-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bundle = Bundle(self.base / "synthetic-unit")

    def failure(self, code, *flags):
        self.bundle.save()
        args = self.bundle.args("--dry-run", *flags) if flags else self.bundle.args()
        with patch.object(database, "transaction") as transaction:
            result = run(args)
        transaction.assert_not_called()
        self.assertEqual(result["state"], "FAILED", result)
        self.assertEqual(result["code"], code, result)
        failure = (self.bundle.report / result["evidence_report"]).read_bytes()
        self.assertFalse(parse_json(failure, "TEST_FAILURE_JSON")["public_eligible"])
        self.assertNotIn(os.fsencode(self.base), failure)
        self.assertEqual(list(self.bundle.artifact.iterdir()), [])
        self.assertEqual(list(self.bundle.staging.iterdir()), [])

    def test_t04_changed_file_with_same_length(self):
        (self.bundle.input / "zones.json").write_bytes(
            b"x" * self.bundle.entry("zones")["byte_size"]
        )
        self.failure("COMPONENT_DIGEST_MISMATCH")

    def test_t05_incorrect_length(self):
        self.bundle.entry("zones")["byte_size"] += 1
        self.failure("COMPONENT_LENGTH_MISMATCH")

    def test_t06_missing_duplicate_and_unknown_roles(self):
        orig = deepcopy(self.bundle.manifest["components"])
        self.bundle.manifest["components"] = [deepcopy(orig[0])]
        self.failure("INVALID_MANIFEST_SCHEMA")
        self.bundle.manifest["components"].append(deepcopy(orig[0]))
        self.failure("DUPLICATE_COMPONENT_ROLE")
        self.bundle.manifest["components"] = [deepcopy(orig[0]), deepcopy(orig[1])]
        self.bundle.manifest["components"][1]["role"] = "occupancy"
        self.failure("INVALID_MANIFEST_SCHEMA")

    def test_t07_bad_json_envelope_and_role(self):
        for raw, code in (
            (b"{", "INVALID_COMPONENT_JSON"),
            (b'{"data":[]}', "INVALID_COMPONENT_ENVELOPE"),
            (
                b'{"data":[{"zones":[]}],"data":[{"zones":[]}]}',
                "INVALID_COMPONENT_JSON",
            ),
            (canonical(envelope("policies", [policy()])), "COMPONENT_ROLE_MISMATCH"),
        ):
            with self.subTest(code=code):
                self.bundle.component("zones", raw)
                self.failure(code)

    def test_t13_timestamp_units_and_unknown_preserved(self):
        entry = self.bundle.entry("zones")
        manifest = load_manifest(canonical(self.bundle.manifest))
        for value, declared, unit, reason in (
            (1774497600.0, None, "seconds", None),
            (1774497600000, None, "milliseconds", None),
            (1000, "milliseconds", "milliseconds", None),
            (None, None, None, "MISSING_SOURCE_TIMESTAMP"),
            ("1774497600", None, None, "INVALID_SOURCE_TIMESTAMP"),
        ):
            with self.subTest(value=value):
                stamp = stage._timestamp({"last_updated": value}, declared)
                # The source parser produces Decimal for a numeric JSON fraction.
                if isinstance(value, float):
                    stamp = stage._timestamp(
                        parse_json(b'{"last_updated":1774497600.0}', "TEST"), declared
                    )
                self.assertEqual(stamp["raw"], value)
                self.assertEqual(stamp["unit"], unit)
                self.assertEqual(stamp["reason"], reason)
                if unit:
                    self.assertEqual(
                        stamp["unit_origin"], "manifest" if declared else "inferred"
                    )
        entry["timestamp_unit"] = "seconds"
        self.assertNotEqual(
            identity(manifest), identity(load_manifest(canonical(self.bundle.manifest)))
        )

    def test_t17_symlinks_traversal_and_special_files(self):
        entry = self.bundle.entry("zones")
        source = self.bundle.input / "zones.json"
        outside = self.base / "private"
        outside.mkdir()
        outside_file = outside / "outside.json"
        source.rename(outside_file)

        entry["relative_path"] = "../private/outside.json"
        self.failure("UNSAFE_INPUT_PATH")
        entry["relative_path"] = str(outside_file)
        self.failure("UNSAFE_INPUT_PATH")
        entry["relative_path"] = "zones.json"
        source.symlink_to(outside_file)
        self.failure("INPUT_PATH_UNAVAILABLE_OR_UNSAFE")
        source.unlink()
        os.mkfifo(source)
        self.failure("NOT_REGULAR_FILE")
        source.unlink()
        (self.bundle.input / "nested").symlink_to(outside, target_is_directory=True)
        entry["relative_path"] = "nested/outside.json"
        self.failure("INPUT_PATH_UNAVAILABLE_OR_UNSAFE")

    def test_t17_output_inside_git_and_control_text_are_rejected(self):
        other = self.base / "other-checkout"
        other.mkdir(mode=0o700)
        (other / ".git").mkdir()
        args = self.bundle.args("--dry-run")
        args.report_root = other
        self.assertEqual(run(args)["code"], "OUTPUT_INSIDE_GIT")
        self.bundle.entry("zones")["relative_path"] = "bad\ud800.json"
        self.failure("INVALID_COMPONENT_TEXT")

    def test_t17_file_swapped_before_and_after_open(self):
        source = self.bundle.input / "zones.json"
        outside = self.base / "outside"
        outside.write_bytes(source.read_bytes())
        old = self.bundle.input / "old"
        original_open = os.open

        def swap_before(path, *args, **kwargs):
            if path == "zones.json":
                source.rename(old)
                source.symlink_to(outside)
            return original_open(path, *args, **kwargs)

        with patch.object(os, "open", swap_before):
            self.failure("INPUT_PATH_UNAVAILABLE_OR_UNSAFE")
        source.unlink()
        old.rename(source)
        original_regular = files.regular

        @contextmanager
        def swap_after(fd, name):
            with original_regular(fd, name) as opened:
                if name == "zones.json":
                    source.rename(old)
                    source.symlink_to(outside)
                    outside.write_bytes(b"not the hashed payload")
                yield opened

        with patch.object(files, "regular", swap_after):
            result = run(self.bundle.args("--dry-run"))
        self.assertEqual(result["state"], "PREFLIGHT_VERIFIED", result)

    def test_t22_opt_in_inventory_on_synthetic_entries(self):
        path = self.bundle.input / "inventory.csv"
        rows = ["source_role,entry_sha256,entry_bytes"]
        for component in self.bundle.manifest["components"]:
            rows.append(
                f"{component['role']},{component['sha256']},{component['byte_size']}"
            )
        path.write_text("\n".join(rows) + "\n")
        result = run(self.bundle.args("--dry-run", "--archive-inventory", path.name))
        self.assertEqual(result["state"], "PREFLIGHT_VERIFIED", result)
        rows[-1] = rows[-1].rsplit(",", 1)[0] + ",1"
        path.write_text("\n".join(rows) + "\n")
        self.failure("ARCHIVE_ENTRY_MISMATCH", "--archive-inventory", path.name)
