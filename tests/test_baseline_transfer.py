from __future__ import annotations

import hashlib
import json
import unittest
from copy import deepcopy

from tap.baseline_transfer import (
    BASELINE_FORMAT,
    BASELINE_SCHEMA_VERSION,
    BaselineValidationError,
    bootstrap_post_from_pre_baseline,
    pre_baseline_json_bytes,
    restore_pre_baseline,
    validate_pre_baseline,
)
from tap.data import questions_for_factors


def baseline_state() -> dict:
    return {
        "assessment_phase": "pre",
        "participant_id": "EDU-P001",
        "project_id": "TAP-LEADERSHIP-001",
        "project_name": "리더십 교육",
        "course_name": "리더십 기본",
        "target_level": "manager",
        "training_date": "2026-09-01",
        "pre_start_date": "2026-08-17",
        "pre_end_date": "2026-08-28",
        "post_start_date": "2026-10-27",
        "post_end_date": "2026-11-10",
        "selected_factors": ["CORE-CO"],
        "assessment_version": "TAP-1.0+abc",
        "question_snapshot_hash": "a" * 64,
        "question_snapshot_codes": ["Q1", "Q2"],
        "target_means": {"CORE-CO": 3.5},
        "organization_priorities": ["CORE-CO"],
        "learner_interests": ["CORE-CO"],
        "delivery_preference": "offline",
        "responses_by_phase": {"pre": {"Q1": 0, "Q2": 5}, "post": {}},
        "assessment_completed_by_phase": {"pre": True, "post": False},
        "current_question_by_phase": {"pre": 1, "post": 0},
    }


def current_bank_baseline_state() -> dict:
    state = baseline_state()
    questions = questions_for_factors(["CORE-CO"])
    snapshot_rows = sorted(
        (
            str(row["question_code"]),
            str(row["revised_text"]),
            str(row.get("scoring_direction", "direct")),
        )
        for row in questions
    )
    snapshot_hash = hashlib.sha256(
        "\n".join("|".join(parts) for parts in snapshot_rows).encode("utf-8")
    ).hexdigest()
    codes = [str(row["question_code"]) for row in questions]
    state.update(
        {
            "assessment_version": f"TAP-1.0+{snapshot_hash[:12]}",
            "question_snapshot_hash": snapshot_hash,
            "question_snapshot_codes": codes,
            "responses_by_phase": {
                "pre": {code: index % 6 for index, code in enumerate(codes)},
                "post": {},
            },
            "current_question_by_phase": {"pre": len(codes) - 1, "post": 0},
        }
    )
    return state


def encode_with_checksum(payload: dict) -> bytes:
    canonical_payload = {key: value for key, value in payload.items() if key != "integrity"}
    canonical = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["integrity"]["checksum"] = hashlib.sha256(canonical).hexdigest()
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def as_v1(raw: bytes) -> bytes:
    payload = json.loads(raw)
    payload["schema_version"] = 1
    for field in (
        "project_id",
        "pre_start_date",
        "post_start_date",
        "post_end_date",
        "organization_priorities",
        "learner_interests",
        "delivery_preference",
    ):
        payload["project"].pop(field)
    return encode_with_checksum(payload)


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

    def test_new_files_use_v2_project_identity_and_schedule(self) -> None:
        payload = json.loads(pre_baseline_json_bytes(baseline_state()))

        self.assertEqual(BASELINE_FORMAT, payload["format"])
        self.assertEqual(BASELINE_SCHEMA_VERSION, payload["schema_version"])
        self.assertEqual("TAP-LEADERSHIP-001", payload["project"]["project_id"])
        self.assertEqual("2026-08-17", payload["project"]["pre_start_date"])
        self.assertEqual("2026-10-27", payload["project"]["post_start_date"])
        self.assertEqual("2026-11-10", payload["project"]["post_end_date"])
        self.assertEqual(["CORE-CO"], payload["project"]["organization_priorities"])
        self.assertEqual(["CORE-CO"], payload["project"]["learner_interests"])
        self.assertEqual("offline", payload["project"]["delivery_preference"])

    def test_bootstrap_configures_fresh_post_session_from_current_bank(self) -> None:
        source = current_bank_baseline_state()
        raw = pre_baseline_json_bytes(source)
        fresh = {
            "assessment_phase": "pre",
            "participant_id": "",
            "selected_factors": [],
            "question_snapshot_hash": "",
            "question_snapshot_codes": [],
            "responses_by_phase": {"pre": {}, "post": {}},
            "assessment_completed_by_phase": {"pre": False, "post": False},
        }

        restored = bootstrap_post_from_pre_baseline(fresh, raw)

        self.assertEqual(2, restored["schema_version"])
        self.assertEqual("post", fresh["assessment_phase"])
        self.assertEqual("post", fresh["current_assessment_phase"])
        self.assertEqual(source["project_id"], fresh["project_id"])
        self.assertEqual(source["project_name"], fresh["project_name"])
        self.assertEqual(source["selected_factors"], fresh["selected_factors"])
        self.assertEqual(source["target_means"], fresh["target_means"])
        self.assertEqual(source["organization_priorities"], fresh["organization_priorities"])
        self.assertEqual(source["learner_interests"], fresh["learner_interests"])
        self.assertEqual(source["delivery_preference"], fresh["delivery_preference"])
        self.assertEqual(source["question_snapshot_hash"], fresh["question_snapshot_hash"])
        self.assertEqual(source["participant_id"], fresh["participant_id"])
        self.assertEqual(
            source["responses_by_phase"]["pre"], fresh["responses_by_phase"]["pre"]
        )
        self.assertEqual({}, fresh["responses_by_phase"]["post"])
        self.assertTrue(fresh["assessment_completed_by_phase"]["pre"])
        self.assertFalse(fresh["assessment_completed_by_phase"]["post"])
        self.assertEqual({}, fresh["responses"])
        self.assertEqual(0, fresh["current_question"])

    def test_bootstrap_accepts_v1_without_requiring_new_schedule_fields(self) -> None:
        source = current_bank_baseline_state()
        raw = as_v1(pre_baseline_json_bytes(source))
        fresh = {
            "assessment_phase": "pre",
            "project_id": "STALE-PROJECT",
            "pre_start_date": "1999-01-01",
            "post_start_date": "1999-02-01",
            "post_end_date": "1999-02-02",
            "organization_priorities": ["STALE"],
            "learner_interests": ["STALE"],
            "delivery_preference": "online",
            "selected_factors": [],
            "question_snapshot_hash": "",
            "question_snapshot_codes": [],
            "responses_by_phase": {"pre": {}, "post": {}},
        }

        restored = bootstrap_post_from_pre_baseline(fresh, raw)

        self.assertEqual(1, restored["schema_version"])
        self.assertEqual("post", fresh["assessment_phase"])
        self.assertEqual(source["participant_id"], fresh["participant_id"])
        self.assertEqual(
            source["responses_by_phase"]["pre"], fresh["responses_by_phase"]["pre"]
        )
        self.assertRegex(fresh["project_id"], r"^TAP-LEGACY-[0-9A-F]{16}$")
        self.assertEqual("2026-08-17", fresh["pre_start_date"])
        self.assertEqual("2026-10-27", fresh["post_start_date"])
        self.assertEqual("2026-11-10", fresh["post_end_date"])
        self.assertEqual([], fresh["organization_priorities"])
        self.assertEqual([], fresh["learner_interests"])
        self.assertEqual("all", fresh["delivery_preference"])
        self.assertEqual(2, len(fresh["baseline_restore_warnings"]))

        second_fresh = {
            "assessment_phase": "pre",
            "selected_factors": [],
            "question_snapshot_hash": "",
            "question_snapshot_codes": [],
            "responses_by_phase": {"pre": {}, "post": {}},
        }
        bootstrap_post_from_pre_baseline(second_fresh, raw)
        self.assertEqual(fresh["project_id"], second_fresh["project_id"])

    def test_bootstrap_rejects_existing_post_data_without_any_mutation(self) -> None:
        source = current_bank_baseline_state()
        raw = pre_baseline_json_bytes(source)
        code = source["question_snapshot_codes"][0]
        contaminated = {
            "assessment_phase": "post",
            "participant_id": "OTHER",
            "selected_factors": [],
            "question_snapshot_hash": "",
            "question_snapshot_codes": [],
            "responses_by_phase": {"pre": {}, "post": {code: 4}},
            "assessment_completed_by_phase": {"pre": False, "post": False},
        }
        before = deepcopy(contaminated)

        with self.assertRaisesRegex(BaselineValidationError, "기존 교육 후 응답"):
            bootstrap_post_from_pre_baseline(contaminated, raw)

        self.assertEqual(before, contaminated)

    def test_bootstrap_rejects_bank_or_existing_snapshot_mismatch_atomically(self) -> None:
        source = current_bank_baseline_state()
        payload = json.loads(pre_baseline_json_bytes(source))
        payload["instrument"]["question_snapshot_hash"] = "b" * 64
        tampered_for_another_bank = encode_with_checksum(payload)
        fresh = {
            "assessment_phase": "pre",
            "selected_factors": [],
            "question_snapshot_hash": "",
            "question_snapshot_codes": [],
            "responses_by_phase": {"pre": {}, "post": {}},
        }
        before = deepcopy(fresh)

        with self.assertRaisesRegex(BaselineValidationError, "현재 문항은행"):
            bootstrap_post_from_pre_baseline(fresh, tampered_for_another_bank)
        self.assertEqual(before, fresh)

        existing = deepcopy(fresh)
        existing["question_snapshot_hash"] = "c" * 64
        before_existing = deepcopy(existing)
        with self.assertRaisesRegex(BaselineValidationError, "다른 문항 스냅샷"):
            bootstrap_post_from_pre_baseline(existing, pre_baseline_json_bytes(source))
        self.assertEqual(before_existing, existing)

    def test_v2_rejects_blank_identity_bad_dates_and_bad_recommendation_context(self) -> None:
        source = current_bank_baseline_state()
        raw_payload = json.loads(pre_baseline_json_bytes(source))
        invalid_cases = (
            ("project_id", "", "project_id"),
            ("project_name", "", "project_name"),
            ("training_date", "2026/09/01", "YYYY-MM-DD"),
            ("pre_start_date", "2026-08-29", "검사 일정"),
            ("pre_completed_at", "2026-08-29", "검사 일정"),
            ("post_start_date", "2026-08-31", "검사 일정"),
            ("post_end_date", "2026-10-01", "검사 일정"),
            ("organization_priorities", "CORE-CO", "조직 우선역량"),
            ("learner_interests", [""], "학습 희망역량"),
            ("delivery_preference", "blended", "교육방식 선호"),
        )
        for field, value, message in invalid_cases:
            with self.subTest(field=field, value=value):
                payload = deepcopy(raw_payload)
                payload["project"][field] = value
                invalid_raw = encode_with_checksum(payload)
                fresh = {
                    "assessment_phase": "pre",
                    "selected_factors": [],
                    "question_snapshot_hash": "",
                    "question_snapshot_codes": [],
                    "responses_by_phase": {"pre": {}, "post": {}},
                }
                before = deepcopy(fresh)
                with self.assertRaisesRegex(BaselineValidationError, message):
                    bootstrap_post_from_pre_baseline(fresh, invalid_raw)
                self.assertEqual(before, fresh)

    def test_v2_generator_derives_nonempty_project_id_before_validation(self) -> None:
        source = baseline_state()
        source["project_id"] = ""

        payload = json.loads(pre_baseline_json_bytes(source))

        self.assertRegex(payload["project"]["project_id"], r"^TAP-[0-9A-F]{16}$")


if __name__ == "__main__":
    unittest.main()
