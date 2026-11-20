"""Validate manifest fields and define their stable capture identity."""

import csv
import io
import re
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

import simplejson as json
from jsonschema import Draft202012Validator

ROLES = ("zones", "policies", "areas")
_SCHEMA = Path(__file__).with_name("manifest.schema.json")
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA.read_bytes()))


class CaptureError(Exception):
    def __init__(self, code, role=None):
        super().__init__(code)
        self.code = code
        self.role = role


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def parse_json(raw, code, role=None):
    try:
        return json.loads(
            raw.decode("utf-8"), use_decimal=True, object_pairs_hook=_unique_object
        )
    except (ValueError, RecursionError):
        raise CaptureError(code, role) from None


def canonical(value):
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            use_decimal=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def digest(data):
    return sha256(data).hexdigest()


def safe_text(value):
    return not any(
        ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF
        for char in value
    )


def _safe_uri(value):
    if not safe_text(value):
        return False
    try:
        uri = urlsplit(value)
        return (
            uri.scheme in ("https", "http")
            and bool(uri.hostname)
            and uri.username is None
            and uri.password is None
            and not uri.query
            and not uri.fragment
            and not any(char.isspace() for char in value)
        )
    except ValueError:
        return False


def _utc(value):
    try:
        return datetime.fromisoformat(value).isoformat().removesuffix("+00:00") + "Z"
    except ValueError:
        raise CaptureError("INVALID_MANIFEST_TIMESTAMP") from None


def load_manifest(raw):
    manifest = parse_json(raw, "INVALID_MANIFEST_JSON")
    if (
        not _VALIDATOR.is_valid(manifest)
        or type(manifest["manifest_schema_version"]) is not int
    ):
        raise CaptureError("INVALID_MANIFEST_SCHEMA")
    if not _safe_uri(manifest["catalog_uri"]):
        raise CaptureError("INVALID_CATALOG_URI")
    if any(
        isinstance(value, str) and not safe_text(value) for value in manifest.values()
    ):
        raise CaptureError("INVALID_MANIFEST_TEXT")
    roles = [entry["role"] for entry in manifest["components"]]
    if len(roles) != len(set(roles)):
        raise CaptureError("DUPLICATE_COMPONENT_ROLE")
    if not {"zones", "policies"}.issubset(roles):
        raise CaptureError("REQUIRED_COMPONENT_MISSING")
    manifest["declared_captured_at_utc"] = _utc(manifest["declared_captured_at_utc"])
    manifest["components"].sort(key=lambda entry: ROLES.index(entry["role"]))
    for entry in manifest["components"]:
        if any(
            isinstance(value, str) and not safe_text(value) for value in entry.values()
        ):
            raise CaptureError("INVALID_COMPONENT_TEXT", entry["role"])
        if type(entry["byte_size"]) is not int:
            raise CaptureError("INVALID_COMPONENT_LENGTH", entry["role"])
        if not _safe_uri(entry["original_source_uri"]):
            raise CaptureError("INVALID_SOURCE_URI", entry["role"])
        if entry.get("source_as_of") is not None:
            entry["source_as_of"] = _utc(entry["source_as_of"])
    return manifest


def identity(manifest):
    values = {
        key: manifest[key]
        for key in (
            "manifest_schema_version",
            "scope_key",
            "publisher_key",
            "dataset_key",
            "source_profile",
            "adapter_version",
            "source_profile_version",
        )
    }
    values["components"] = [
        {
            key: component.get(key)
            for key in (
                "role",
                "sha256",
                "byte_size",
                "source_format",
                "source_crs",
                "source_as_of",
                "timestamp_unit",
            )
        }
        for component in manifest["components"]
    ]
    capture_digest = digest(canonical(values))
    return capture_digest, batch_id_for_digest(capture_digest)


def batch_id_for_digest(capture_digest):
    return uuid5(NAMESPACE_URL, f"curbos:cds-capture:v1:{capture_digest}")


def verify_inventory(raw, manifest):
    """Compare an explicitly selected archive inventory with extracted entries."""
    try:
        inventory = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        for entry in manifest["components"]:
            matches = [
                row
                for row in inventory
                if row["source_role"] == entry["role"]
                and row["entry_sha256"] == entry["sha256"]
                and re.fullmatch(r"[0-9]+", row["entry_bytes"])
                and int(row["entry_bytes"]) == entry["byte_size"]
            ]
            if len(matches) != 1:
                raise CaptureError("ARCHIVE_ENTRY_MISMATCH", entry["role"])
    except (ValueError, KeyError, TypeError, csv.Error):
        raise CaptureError("INVALID_ARCHIVE_INVENTORY") from None
