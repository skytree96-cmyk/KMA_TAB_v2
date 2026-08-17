from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tap.data import questions_for_factors


ROOT = Path(__file__).resolve().parents[1]


class PrePostPageTests(unittest.TestCase):
    def test_project_setup_collects_course_schedule_and_uses_split_phase_navigation(self) -> None:
        source = (ROOT / "pages" / "1_project_setup.py").read_text(encoding="utf-8")
        for label in (
            "교육과정명",
            "교육일",
            "교육 전 검사 시작일",
            "교육 전 검사 마감일",
            "교육 후 검사 시작일",
            "교육 후 검사 마감일",
        ):
            self.assertIn(label, source)
        self.assertIn("56 <= post_delay_days <= 70", source)
        self.assertIn("activate_assessment_phase", source)
        self.assertIn("왼쪽 메뉴의 ‘교육 전 검사’와 ‘교육 후 검사’", source)
        self.assertNotIn('"현재 참여자에게 열 검사"', source)

    def test_project_identity_change_invalidates_saved_assessments(self) -> None:
        source = (ROOT / "pages" / "1_project_setup.py").read_text(encoding="utf-8")
        self.assertIn("has_saved_assessment", source)
        self.assertIn('str(st.session_state.get("project_name", "")) != next_project_name', source)
        self.assertIn("stored_schedule != next_schedule", source)
        self.assertIn('st.session_state.project_id = "TAP-"', source)

    def test_project_identity_change_clears_previous_participant_pairing(self) -> None:
        app = AppTest.from_file(str(ROOT / "pages" / "1_project_setup.py"), default_timeout=30)
        app.session_state["project_id"] = "TAP-OLD"
        app.session_state["project_name"] = "기존 프로젝트"
        app.session_state["project_name_input"] = "새 프로젝트"
        app.session_state["participant_id"] = "OLD-P001"
        app.session_state["_participant_id_input"] = "OLD-P001"
        app.run()

        save = next(
            item for item in app.button if item.label == "설정 저장 후 교육 전 검사 시작"
        )
        with patch("streamlit.switch_page"):
            save.click()
            app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertEqual("", app.session_state["participant_id"])
        self.assertNotIn("_participant_id_input", app.session_state)

    def test_resaving_same_project_keeps_participant_pairing(self) -> None:
        app = AppTest.from_file(str(ROOT / "pages" / "1_project_setup.py"), default_timeout=30).run()
        with patch("streamlit.switch_page"):
            next(
                item for item in app.button if item.label == "설정 저장 후 교육 전 검사 시작"
            ).click()
            app.run()

        project_id = app.session_state["project_id"]
        app.session_state["participant_id"] = "KEEP-P001"
        app.session_state["_participant_id_input"] = "KEEP-P001"
        with patch("streamlit.switch_page"):
            next(
                item for item in app.button if item.label == "설정 저장 후 교육 전 검사 시작"
            ).click()
            app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertEqual(project_id, app.session_state["project_id"])
        self.assertEqual("KEEP-P001", app.session_state["participant_id"])
        self.assertEqual("KEEP-P001", app.session_state["_participant_id_input"])
        self.assertEqual("pre", app.session_state["assessment_phase"])

    def test_project_setup_preserves_custom_target_and_delivery_on_reentry(self) -> None:
        app = AppTest.from_file(str(ROOT / "pages" / "1_project_setup.py"), default_timeout=30)
        app.session_state["target_means"] = {"CORE-CO": 4.2}
        app.session_state["delivery_preference"] = "online"
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        target = next(item for item in app.slider if item.label == "조직 기대 행동빈도(1~5)")
        delivery = next(item for item in app.radio if item.label == "선호 교육방식")
        self.assertEqual(4.2, target.value)
        self.assertEqual("online", delivery.value)

    def test_assessment_uses_same_eight_week_instruction_for_both_phases(self) -> None:
        source = (ROOT / "pages" / "2_assessment.py").read_text(encoding="utf-8")
        self.assertIn("사전·사후 모두 동일하게 최근 8주", source)
        self.assertIn('class="tap-period-pill">최근 8주</span>', source)
        self.assertNotIn("최근 4주", source)
        self.assertIn("sync_assessment_phase", source)

    def test_public_schedule_override_is_presented_as_real_submission(self) -> None:
        setup_source = (ROOT / "pages" / "1_project_setup.py").read_text(encoding="utf-8")
        assessment_source = (ROOT / "pages" / "2_assessment.py").read_text(encoding="utf-8")
        self.assertIn("공개 시연에서 검사기간 예외 허용", setup_source)
        self.assertIn("실제 검사 제출이 가능합니다", assessment_source)
        self.assertNotIn("검사기간 밖 미리보기", setup_source)
        self.assertNotIn("미리보기 모드", assessment_source)

    def test_completed_post_items_open_transfer_environment_form(self) -> None:
        questions = questions_for_factors(["CORE-CO"])
        responses = {str(row["question_code"]): 3 for row in questions}
        app = AppTest.from_file(str(ROOT / "pages" / "2_assessment.py"), default_timeout=30).run()
        app.session_state["selected_factors"] = ["CORE-CO"]
        app.session_state["assessment_phase"] = "post"
        app.session_state["responses_by_phase"] = {"pre": responses, "post": responses}
        app.session_state["assessment_completed_by_phase"] = {"pre": True, "post": False}
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        transfer_labels = {item.label for item in app.radio}
        self.assertIn("교육에서 배운 내용을 업무에 적용할 기회가 있었다.", transfer_labels)
        self.assertIn("상사·리더가 배운 내용을 적용하도록 지원했다.", transfer_labels)
        self.assertIn("적용에 필요한 도구·정보·권한이 충분했다.", transfer_labels)
        self.assertIn("업무시간과 프로세스가 새로운 방식을 적용하기에 적합했다.", transfer_labels)
        self.assertTrue(any(item.label == "적용을 방해한 요인(복수 선택)" for item in app.multiselect))
        self.assertTrue(any(item.label == "교육 후 검사 완료" for item in app.button))

    def test_save_and_next_advances_to_the_following_question(self) -> None:
        questions = questions_for_factors(["CORE-CO"])
        self.assertGreater(len(questions), 1)
        app = AppTest.from_file(str(ROOT / "pages" / "2_assessment.py"), default_timeout=30).run()
        app.session_state["selected_factors"] = ["CORE-CO"]
        app.session_state["participant_id"] = "TEST-P001"
        app.run()

        first_code = str(questions[0]["question_code"])
        app.radio[0].set_value(3)
        next(button for button in app.button if button.label == "다음 문항 →").click()
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertEqual(1, app.session_state["current_question"])
        self.assertEqual(1, app.session_state["current_question_by_phase"]["pre"])
        self.assertEqual(3, app.session_state["responses_by_phase"]["pre"][first_code])

    def test_blank_participant_id_keeps_question_visible_and_blocks_save(self) -> None:
        app = AppTest.from_file(str(ROOT / "pages" / "2_assessment.py"), default_timeout=30).run()
        app.session_state["selected_factors"] = ["CORE-CO"]
        app.session_state["participant_id"] = ""
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertTrue(any(item.label == "교육 참여자 ID" for item in app.text_input))
        self.assertTrue(app.radio, "ID가 비어 있어도 질문과 응답 선택지는 보여야 합니다.")
        self.assertTrue(any(item.label == "다음 문항 →" for item in app.button))
        self.assertTrue(any("ID 입력 전에는 응답을 저장할 수 없습니다" in str(item.value) for item in app.warning))

        app.radio[0].set_value(3)
        next(button for button in app.button if button.label == "다음 문항 →").click()
        app.run()

        self.assertEqual(0, app.session_state["current_question"])
        self.assertEqual({}, app.session_state["responses_by_phase"]["pre"])
        self.assertEqual(3, app.radio[0].value)
        self.assertTrue(any("교육 참여자 ID를 입력한 뒤" in str(item.value) for item in app.error))

    def test_completed_pre_phase_restores_locked_participant_id_for_post(self) -> None:
        app = AppTest.from_file(str(ROOT / "pages" / "2_assessment.py"), default_timeout=30).run()
        app.session_state["selected_factors"] = ["CORE-CO"]
        app.session_state["participant_id"] = "EDU-P001"
        app.session_state["assessment_phase"] = "post"
        app.session_state["assessment_completed_by_phase"] = {"pre": True, "post": False}
        # Match Streamlit's cleanup after leaving the pre-assessment page.
        if "_participant_id_input" in app.session_state:
            del app.session_state["_participant_id_input"]
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        participant_id_input = next(item for item in app.text_input if item.label == "교육 참여자 ID")
        self.assertEqual("EDU-P001", participant_id_input.value)
        self.assertTrue(participant_id_input.disabled)
        self.assertEqual("EDU-P001", app.session_state["participant_id"])

    def test_post_without_pre_offers_baseline_json_upload(self) -> None:
        app = AppTest.from_file(str(ROOT / "pages" / "2_assessment.py"), default_timeout=30).run()
        app.session_state["selected_factors"] = ["CORE-CO"]
        app.session_state["assessment_phase"] = "post"
        app.session_state["assessment_completed_by_phase"] = {"pre": False, "post": False}
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertTrue(
            any(item.label == "교육 전 검사 기준파일(JSON)" for item in app.get("file_uploader"))
        )
        self.assertFalse(app.radio, "기준파일 복원 전에는 사후 문항을 시작하면 안 됩니다.")
        self.assertTrue(any("분실한 경우" in str(item.value) for item in app.caption))

    def test_fresh_participant_can_import_baseline_before_project_setup(self) -> None:
        app = AppTest.from_file(str(ROOT / "pages" / "2_assessment.py"), default_timeout=30).run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertTrue(any("교육 후 검사 이어하기" in str(item.value) for item in app.markdown))
        self.assertTrue(
            any(item.label == "교육 전 검사 기준파일(JSON)" for item in app.get("file_uploader"))
        )
        self.assertTrue(
            any(item.label == "교육평가 프로젝트 설정으로 이동" for item in app.button)
        )


if __name__ == "__main__":
    unittest.main()
