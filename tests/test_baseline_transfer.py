from __future__ import annotations

import json
import unittest
from copy import deepcopy

from tap.baseline_transfer import (
    BaselineValidationError,
    pre_baseline_json_bytes,
    restore_pre_baseline,
    validate_pre_baseline,
)


def baseline_state() -> dict:
    return {
        "assessment_phase": "pre",
        "participant_id": "EDU-P001",
        "project_name": "리더십 교육",
        "course_name": "리더십 기본",
        "target_level": "manager",
        "training_date": "2026-09-01",
        "pre_end_date": "2026-08-28",
        "selected_factors": ["CORE-CO"],
        "assessment_version": "TAP-1.0+abc",
        "question_snapshot_hash": "a" * 64,
        "question_snapshot_codes": ["Q1", "Q2"],
        "target_means": {"CORE-CO": 3.5},
        "responses_by_phase": {"pre": {"Q1": 0, "Q2": 5}, "post": {}},
        "assessment_completed_by_phase": {"pre": True, "post": False},
        "current_question_by_phase": {"pre": 1, "post": 0},
    }


class BaselineTransferTests(unittest.TestCase):
    def test_round_trip_restores_canonical_pre_without_touching_post(self) -> None:
        source = baseline_state()
        raw = pre_baseline_json_bytes(source)
        target = deepcopy(source)
        target.update(
            {
                "assessment_phase": "post",
                "participant_id": "",
                "responses_by_phase": {"pre": {}, "post": {"Q1": 4}},
                "assessment_completed_by_phase": {"pre": False, "post": False},
                "current_question_by_phase": {"pre": 0, "post": 1},
            }
        )

        restored = restore_pre_baseline(target, raw)

        self.assertEqual("EDU-P001", target["participant_id"])
        self.assertEqual("EDU-P001", target["_participant_id_input"])
        self.assertEqual({"Q1": 0, "Q2": 5}, target["responses_by_phase"]["pre"])
        self.assertEqual({"Q1": 4}, target["responses_by_phase"]["post"])
        self.assertTrue(target["assessment_completed_by_phase"]["pre"])
        self.assertEqual("checksum-only-not-a-signature", restored["integrity"]["assurance"])

    def test_rejects_tampering_and_wrong_instrument(self) -> None:
        source = baseline_state()
        payload = json.loads(pre_baseline_json_bytes(source))
        payload["responses"]["Q1"] = 5
        target = deepcopy(source)
        target["assessment_phase"] = "post"

        with self.assertRaisesRegex(BaselineValidationError, "변경되었거나 손상"):
            validate_pre_baseline(json.dumps(payload), target)

        wrong = deepcopy(target)
        wrong["assessment_version"] = "TAP-2.0"
        with self.assertRaisesRegex(BaselineValidationError, "검사 버전"):
            validate_pre_baseline(pre_baseline_json_bytes(source), wrong)

    def test_rejects_incomplete_extra_or_invalid_scores(self) -> None:
        for responses in (
            {"Q1": 3},
            {"Q1": 3, "Q2": 4, "Q3": 2},
            {"Q1": 3, "Q2": 6},
            {"Q1": 3, "Q2": 2.5},
            {"Q1": 3, "Q2": True},
        ):
            with self.subTest(responses=responses):
                state = baseline_state()
                state["responses_by_phase"]["pre"] = responses
                with self.assertRaises(BaselineValidationError):
                    pre_baseline_json_bytes(state)

    def test_requires_post_phase_and_matching_factors_snapshot(self) -> None:
        source = baseline_state()
        raw = pre_baseline_json_bytes(source)

        with self.assertRaisesRegex(BaselineValidationError, "교육 후 검사"):
            validate_pre_baseline(raw, source)

        target = deepcopy(source)
        target["assessment_phase"] = "post"
        target["selected_factors"] = ["OTHER"]
        with self.assertRaisesRegex(BaselineValidationError, "선택 역량"):
            validate_pre_baseline(raw, target)

        target = deepcopy(source)
        target["assessment_phase"] = "post"
        target["question_snapshot_hash"] = "b" * 64
        with self.assertRaisesRegex(BaselineValidationError, "문항 스냅샷"):
            validate_pre_baseline(raw, target)

    def test_rejects_a_baseline_from_another_project(self) -> None:
        source = baseline_state()
        raw = pre_baseline_json_bytes(source)
        target = deepcopy(source)
        target["assessment_phase"] = "post"
        target["project_name"] = "다른 교육 프로젝트"

        with self.assertRaisesRegex(BaselineValidationError, "프로젝트명"):
            validate_pre_baseline(raw, target)

        target = deepcopy(source)
        target["assessment_phase"] = "post"
        target["target_means"] = {"CORE-CO": 4.0}
        with self.assertRaisesRegex(BaselineValidationError, "목표값"):
            validate_pre_baseline(raw, target)

    def test_rejects_unknown_fields_and_conflicting_post_participant(self) -> None:
        source = baseline_state()
        payload = json.loads(pre_baseline_json_bytes(source))
        payload["unexpected"] = "value"
        target = deepcopy(source)
        target["assessment_phase"] = "post"
        with self.assertRaisesRegex(BaselineValidationError, "필드 구성"):
            validate_pre_baseline(json.dumps(payload), target)

        target = deepcopy(source)
        target.update(
            {
                "assessment_phase": "post",
                "participant_id": "OTHER-P002",
                "responses_by_phase": {"pre": {}, "post": {"Q1": 3}},
            }
        )
        with self.assertRaisesRegex(BaselineValidationError, "다른 참여자 ID"):
            restore_pre_baseline(target, pre_baseline_json_bytes(source))


if __name__ == "__main__":
    unittest.main()
