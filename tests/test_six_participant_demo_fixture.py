from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.seed_six_participant_demo import (
    SYNTHETIC_FACTOR_CODES,
    SYNTHETIC_PROJECT_ID,
    apply_fixture,
    build_fixture_bundle,
    fixture_files,
    validate_fixture_bundle,
    write_fixture_bundle,
)
from tap.tenant import CompanyIdentity, derive_company_identity, hash_company_access_code


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

    def test_apply_reviews_pending_company_without_a_management_code(self) -> None:
        salt = "code-free-review-test-salt"
        disposable_proof = "0" * 10
        identity = derive_company_identity(
            salt=salt,
            company_name="TAP 합성 예시기업",
            business_registration_number=disposable_proof,
        )
        digest = hash_company_access_code(
            identity.company_id, disposable_proof, salt
        )
        bundle = build_fixture_bundle(
            company_identity=identity,
            company_access_digest=digest,
            participant_salt=salt,
        )
        constructor_kwargs: list[dict[str, str]] = []
        review_calls: list[tuple[str, str]] = []

        class RecordingStore:
            def __init__(self, _config, **kwargs):
                constructor_kwargs.append(dict(kwargs))

            def request_company_registration(self, _identity, _digest):
                return {**bundle["company"], "approval_status": "pending"}

            def review_company_registration(self, company_id, decision, **_kwargs):
                review_calls.append((company_id, decision))
                return {**bundle["company"], "approval_status": "approved"}

            def save_project(self, project):
                return dict(project)

            def save_submission(self, submission):
                return dict(submission)

        # The config deliberately exposes only the participant write gate;
        # company review does not receive a second secret.
        config = SimpleNamespace(salt=salt, participant_code="participant-code")
        with patch(
            "scripts.seed_six_participant_demo.GitHubDemoStore", RecordingStore
        ):
            applied = apply_fixture(
                bundle,
                config=config,
                disposable_company_proof=disposable_proof,
            )

        self.assertEqual(
            [(identity.company_id, "approved")],
            review_calls,
        )
        self.assertEqual(
            [
                {"company_access_code": disposable_proof},
                {},
                {"company_access_code": disposable_proof},
                {"participant_access_code": "participant-code"},
            ],
            constructor_kwargs,
        )
        self.assertEqual(6, len(applied["submissions"]))


if __name__ == "__main__":
    unittest.main()
