from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.seed_six_participant_demo import (
    SYNTHETIC_FACTOR_CODES,
    SYNTHETIC_PROJECT_ID,
    build_fixture_bundle,
    fixture_files,
    validate_fixture_bundle,
    write_fixture_bundle,
)
from tap.tenant import CompanyIdentity


class SixParticipantDemoFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = CompanyIdentity(
            company_id="org_" + "1" * 64,
            company_name="TAP 합성 예시기업",
            identity_source="business_registration",
        )
        self.digest = "cac_" + "2" * 64
        self.bundle = build_fixture_bundle(
            company_identity=self.identity,
            company_access_digest=self.digest,
            participant_salt="deterministic-fixture-test-salt",
        )

    def test_bundle_is_deterministic_complete_and_privacy_safe(self) -> None:
        again = build_fixture_bundle(
            company_identity=self.identity,
            company_access_digest=self.digest,
            participant_salt="deterministic-fixture-test-salt",
        )
        self.assertEqual(self.bundle, again)
        self.assertEqual("approved", self.bundle["company"]["approval_status"])
        self.assertEqual(SYNTHETIC_PROJECT_ID, self.bundle["project"]["project_id"])
        self.assertEqual(list(SYNTHETIC_FACTOR_CODES), self.bundle["project"]["selected_factors"])
        self.assertEqual(6, len(self.bundle["submissions"]))

        encoded = json.dumps(self.bundle, ensure_ascii=False)
        self.assertNotIn("participant_id", encoded)
        self.assertNotIn("SYNTHETIC-P", encoded)
        self.assertNotIn("business_registration_number", encoded)
        self.assertNotIn("kma_assigned_code", encoded)
        self.assertEqual(
            6,
            len({row["participant_key"] for row in self.bundle["submissions"]}),
        )
        for submission in self.bundle["submissions"]:
            self.assertTrue(submission["phases"]["pre"]["completed"])
            self.assertTrue(submission["phases"]["post"]["completed"])
            self.assertEqual(
                set(self.bundle["project"]["question_snapshot_codes"]),
                set(submission["phases"]["pre"]["responses"]),
            )
            self.assertEqual(
                set(self.bundle["project"]["question_snapshot_codes"]),
                set(submission["phases"]["post"]["responses"]),
            )

    def test_validation_publishes_all_eight_axes_at_n_six(self) -> None:
        summary = validate_fixture_bundle(self.bundle)
        self.assertEqual(6, summary["paired_participant_count"])
        self.assertEqual(8, summary["published_factor_count"])
        self.assertEqual(8, summary["radar_axis_count"])
        self.assertEqual([], summary["warnings"])

    def test_local_mirror_uses_exact_tenant_paths(self) -> None:
        files = fixture_files(self.bundle)
        self.assertEqual(9, len(files))
        self.assertIn(
            f"tap-demo/v1/project-index/{SYNTHETIC_PROJECT_ID}.json",
            files,
        )
        company_root = f"tap-demo/v1/companies/{self.identity.company_id}"
        self.assertIn(f"{company_root}/company.json", files)
        self.assertIn(
            f"{company_root}/projects/{SYNTHETIC_PROJECT_ID}.json",
            files,
        )
        submission_paths = [path for path in files if "/submissions/" in path]
        self.assertEqual(6, len(submission_paths))

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            written = write_fixture_bundle(self.bundle, output)
            self.assertEqual(9, len(written))
            self.assertTrue(all(path.is_file() for path in written))
            registry = json.loads(
                (output / company_root / "company.json").read_text(encoding="utf-8")
            )
            self.assertEqual("approved", registry["approval_status"])


if __name__ == "__main__":
    unittest.main()
