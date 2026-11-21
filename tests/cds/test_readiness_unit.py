"""Test the v1 readiness policy independently of PostgreSQL and capture."""

import unittest

from data.cds_capture.manifest import CaptureError
from data.cds_readiness.review import checklist, outcomes


class ReadinessPolicy(unittest.TestCase):
    def test_absent_review_stays_unknown_and_cannot_authorize(self):
        items, claim, withheld = checklist(None, {}, None, ["zones:2"])
        for item in items.values():
            self.assertEqual(item, {"state": "UNKNOWN", "evidence_ref": None})
        self.assertEqual(claim, "SOURCE_REPORTED_ONLY")
        result = outcomes(
            items,
            {
                "registered_rights_status": "UNKNOWN",
                "registry_rights_reference_present": False,
            },
            {
                "scope_review_status": "UNREVIEWED",
                "review_recorded": False,
                "boundary_sha256": None,
                "not_fully_covered_zone_ids": None,
            },
            claim,
            {"review_required": ["zones:2"], "zones": [{}]},
            withheld,
        )
        self.assertEqual(
            {key: value["status"] for key, value in result.items()},
            {
                "TECHNICAL_READINESS": "PASS",
                "EVIDENCE_READINESS": "BLOCKED",
                "PUBLICATION_READINESS": "BLOCKED",
            },
        )
        self.assertIn(
            "REVIEW_REQUIRED_RECORDS_LACK_DOCUMENTED_DISPOSITION",
            [item["code"] for item in result["EVIDENCE_READINESS"]["reasons"]],
        )
        self.assertIn(
            "SYNTHETIC_ONLY_ACTIVATION_AND_NO_REAL_SERVING",
            [item["code"] for item in result["PUBLICATION_READINESS"]["reasons"]],
        )

    def test_checklist_can_only_withhold_exact_review_required_records(self):
        evidence = {
            "schema_version": 1,
            "binding": {"batch_id": "synthetic"},
            "items": {},
            "withheld_records": {"zones:4": "evidence:synthetic-withholding"},
        }
        with self.assertRaisesRegex(CaptureError, "INVALID_REVIEW_DISPOSITION"):
            checklist(evidence, evidence["binding"], None, ["zones:2"])
        _, _, result = checklist(evidence, evidence["binding"], None, ["zones:4"])
        self.assertEqual(result, {"zones:4": "evidence:synthetic-withholding"})
