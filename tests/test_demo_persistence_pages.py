from __future__ import annotations

import hashlib
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

from tap.data import questions_for_factors
from tap.github_demo_store import (
    DemoStoreConfig,
    project_payload_from_state,
    submission_payload_from_state,
)


ROOT = Path(__file__).resolve().parents[1]


def project_state(project_id: str = "TAP-DEMO-PAGE-TEST") -> dict[str, object]:
    project_name = "페이지 저장 검증"
    selected = ["CORE-CO"]
    questions = sorted(
        questions_for_factors(selected),
        key=lambda row: hashlib.sha256(
            f"{project_name}|{row['question_code']}".encode("utf-8")
        ).hexdigest(),
    )
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
    today = date.today()
    training = today + timedelta(days=30)
    return {
        "project_id": project_id,
        "project_name": project_name,
        "course_name": "테스트 교육",
        "project_start_date": today.isoformat(),
        "project_end_date": (today + timedelta(days=7)).isoformat(),
        "training_date": training.isoformat(),
        "pre_start_date": today.isoformat(),
        "pre_end_date": (today + timedelta(days=7)).isoformat(),
        "post_start_date": (training + timedelta(days=56)).isoformat(),
        "post_end_date": (training + timedelta(days=63)).isoformat(),
        "allow_schedule_override": True,
        "target_level": "manager",
        "selected_factors": selected,
        "target_means": {"CORE-CO": 3.5},
        "organization_priorities": ["CORE-CO"],
        "learner_interests": [],
        "training_cause": "mixed_or_unknown",
        "delivery_preference": "all",
        "assessment_version": f"TAP-1.0+{snapshot_hash[:12]}",
        "question_snapshot_hash": snapshot_hash,
        "question_snapshot_codes": [str(row["question_code"]) for row in questions],
        "current_assessment_phase": "pre",
    }


class DemoPersistencePageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.access_code = "planning-test-access"
        self.config = DemoStoreConfig(
            enabled=True,
            owner="example",
            repo="tap-demo",
            token="test-token",
            salt="test-participant-salt",
            access_code=self.access_code,
        )
        self.store = MagicMock()
        self.patches = (
            patch(
                "tap.github_demo_store.DemoStoreConfig.from_sources",
                return_value=self.config,
            ),
            patch("tap.github_demo_store.GitHubDemoStore", return_value=self.store),
        )
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()

    def test_project_save_publishes_one_allowlisted_snapshot(self) -> None:
        app = AppTest.from_file(
            str(ROOT / "pages" / "1_project_setup.py"), default_timeout=30
        ).run()
        next(
            item for item in app.text_input if item.label == "기획검증 접속코드"
        ).set_value(self.access_code)
        with patch("streamlit.switch_page"):
            next(
                item
                for item in app.button
                if item.label == "설정 저장 후 실제 검사 시작"
            ).click()
            app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.store.save_project.assert_called_once()
        payload = self.store.save_project.call_args.args[0]
        self.assertEqual("project", payload["record_type"])
        self.assertNotIn("participant_id", payload)
        self.assertTrue(app.session_state["project_id"].startswith("TAP-"))

    def test_project_save_without_access_code_keeps_session_and_skips_github(self) -> None:
        app = AppTest.from_file(
            str(ROOT / "pages" / "1_project_setup.py"), default_timeout=30
        ).run()
        with patch("streamlit.switch_page"):
            next(
                item
                for item in app.button
                if item.label == "설정 저장 후 실제 검사 시작"
            ).click()
            app.run()

        self.store.save_project.assert_not_called()
        self.assertTrue(app.session_state["demo_store_project_pending"])
        self.assertTrue(app.session_state["project_id"].startswith("TAP-"))

    def test_project_code_load_restores_only_valid_project_fields(self) -> None:
        payload = project_payload_from_state(project_state())
        payload["participant_id"] = "MUST-NOT-RESTORE"
        payload["arbitrary_session_key"] = "MUST-NOT-RESTORE"
        self.store.load_project.return_value = payload

        app = AppTest.from_file(
            str(ROOT / "pages" / "2_assessment.py"), default_timeout=30
        ).run()
        code_input = next(
            item for item in app.text_input if item.label == "프로젝트 코드"
        )
        code_input.set_value(str(payload["project_id"]))
        next(
            item for item in app.button if item.label == "테스트 프로젝트 불러오기"
        ).click()
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.store.load_project.assert_called_once_with(payload["project_id"])
        self.assertEqual(payload["project_id"], app.session_state["project_id"])
        self.assertEqual(["CORE-CO"], app.session_state["selected_factors"])
        self.assertEqual("", app.session_state["participant_id"])
        self.assertNotIn("arbitrary_session_key", app.session_state)
        self.assertTrue(any(item.label == "교육 참여자 ID" for item in app.text_input))

    def test_post_project_code_and_id_restore_pre_without_json(self) -> None:
        state = project_state("TAP-DEMO-POST-LOAD")
        state["current_assessment_phase"] = "post"
        state["assessment_phase"] = "post"
        project_payload = project_payload_from_state(state)
        questions = questions_for_factors(["CORE-CO"])
        responses = {str(row["question_code"]): 3 for row in questions}
        submission_state = {
            **state,
            "participant_id": "POST-TEST-P001",
            "responses_by_phase": {"pre": responses, "post": {}},
            "assessment_completed_by_phase": {"pre": True, "post": False},
            "assessment_completed_at_by_phase": {
                "pre": date.today().isoformat(),
                "post": None,
            },
            "assessment_started_at_by_phase": {"pre": 100.0, "post": None},
            "duration_seconds_by_phase": {"pre": 120.0, "post": None},
            "post_transfer_responses": {},
        }
        submission_payload = submission_payload_from_state(
            submission_state, salt=self.config.salt
        )
        self.store.load_project.return_value = project_payload
        self.store.load_submission.return_value = submission_payload

        app = AppTest.from_file(
            str(ROOT / "pages" / "2_assessment.py"), default_timeout=30
        ).run()
        next(item for item in app.text_input if item.label == "프로젝트 코드").set_value(
            str(project_payload["project_id"])
        )
        next(
            item for item in app.button if item.label == "테스트 프로젝트 불러오기"
        ).click()
        app.run()

        self.assertEqual("post", app.session_state["assessment_phase"])
        participant_input = next(
            item for item in app.text_input if item.label == "교육 참여자 ID"
        )
        participant_input.set_value("POST-TEST-P001")
        next(
            item for item in app.text_input if item.label == "기획검증 접속코드"
        ).set_value("")
        next(
            item
            for item in app.button
            if item.label == "저장된 교육 전 결과 불러오기"
        ).click()
        app.run()

        self.store.load_submission.assert_not_called()
        self.assertFalse(app.session_state["assessment_completed_by_phase"]["pre"])

        next(
            item for item in app.text_input if item.label == "기획검증 접속코드"
        ).set_value(self.access_code)
        next(
            item
            for item in app.button
            if item.label == "저장된 교육 전 결과 불러오기"
        ).click()
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertTrue(app.session_state["assessment_completed_by_phase"]["pre"])
        self.assertEqual(responses, app.session_state["responses_by_phase"]["pre"])
        expected_key = submission_payload["participant_key"]
        self.store.load_submission.assert_called_once_with(
            project_payload["project_id"], expected_key
        )
        locked_id = next(
            item for item in app.text_input if item.label == "교육 참여자 ID"
        )
        self.assertEqual("POST-TEST-P001", locked_id.value)
        self.assertTrue(locked_id.disabled)
        self.assertTrue(any(item.label == "응답" for item in app.radio))

    def _assessment_app(self, phase: str) -> tuple[AppTest, list[dict]]:
        state = project_state()
        questions = questions_for_factors(["CORE-CO"])
        by_code = {str(row["question_code"]): row for row in questions}
        ordered = [by_code[code] for code in state["question_snapshot_codes"]]
        responses = {str(row["question_code"]): 3 for row in ordered}

        app = AppTest.from_file(
            str(ROOT / "pages" / "2_assessment.py"), default_timeout=30
        ).run()
        for key, value in state.items():
            app.session_state[key] = value
        app.session_state["participant_id"] = "RAW-PARTICIPANT-ID"
        app.session_state["assessment_phase"] = phase
        app.session_state["responses_by_phase"] = {
            "pre": dict(responses),
            "post": dict(responses) if phase == "post" else {},
        }
        app.session_state["assessment_completed_by_phase"] = {
            "pre": phase == "post",
            "post": False,
        }
        app.session_state["assessment_completed_at_by_phase"] = {
            "pre": date.today().isoformat() if phase == "post" else None,
            "post": None,
        }
        app.session_state["current_question_by_phase"] = {
            "pre": len(ordered) - 1,
            "post": len(ordered) - 1,
        }
        if phase == "pre":
            last_code = str(ordered[-1]["question_code"])
            app.session_state["responses_by_phase"]["pre"].pop(last_code)
            app.session_state["responses"] = app.session_state["responses_by_phase"]["pre"]
        else:
            app.session_state["responses"] = app.session_state["responses_by_phase"]["post"]
        app.session_state["current_question"] = len(ordered) - 1
        app.session_state["assessment_completed"] = False
        next(
            item for item in app.text_input if item.label == "기획검증 접속코드"
        ).set_value(self.access_code)
        app.run()
        return app, ordered

    def test_pre_completion_saves_once_without_raw_participant_id(self) -> None:
        app, _ = self._assessment_app("pre")
        question_radio = next(item for item in app.radio if item.label == "응답")
        question_radio.set_value(4)
        next(item for item in app.button if item.label == "교육 전 결과 보기").click()
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.store.save_submission.assert_called_once()
        payload = self.store.save_submission.call_args.args[0]
        self.assertTrue(payload["phases"]["pre"]["completed"])
        self.assertFalse(payload["phases"]["post"]["completed"])
        self.assertNotIn("RAW-PARTICIPANT-ID", repr(payload))
        self.assertTrue(str(payload["participant_key"]).startswith("p_"))

    def test_post_completion_includes_transition_and_failure_is_retryable(self) -> None:
        self.store.save_submission.side_effect = RuntimeError("temporary")
        app, _ = self._assessment_app("post")
        for item in app.radio:
            if item.label != "응답":
                item.set_value(4)
        next(item for item in app.button if item.label == "교육 후 검사 완료").click()
        app.run()

        self.assertTrue(app.session_state["assessment_completed_by_phase"]["post"])
        self.assertEqual("post", app.session_state["demo_store_submission_pending_phase"])
        self.assertTrue(
            any(item.label == "GitHub 검사결과 저장 다시 시도" for item in app.button)
        )
        self.store.save_submission.side_effect = None
        next(
            item
            for item in app.button
            if item.label == "GitHub 검사결과 저장 다시 시도"
        ).click()
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertEqual(2, self.store.save_submission.call_count)
        payload = self.store.save_submission.call_args.args[0]
        self.assertTrue(payload["phases"]["post"]["completed"])
        self.assertEqual(4, payload["transition_responses"]["application_opportunity"])
        self.assertIsNone(app.session_state["demo_store_submission_pending_phase"])


if __name__ == "__main__":
    unittest.main()
