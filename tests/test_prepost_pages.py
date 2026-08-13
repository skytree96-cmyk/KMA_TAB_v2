from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tap.data import questions_for_factors


ROOT = Path(__file__).resolve().parents[1]


class PrePostPageTests(unittest.TestCase):
    def test_project_setup_collects_course_schedule_and_active_phase(self) -> None:
        source = (ROOT / "pages" / "1_project_setup.py").read_text(encoding="utf-8")
        for label in (
            "교육과정명",
            "교육일",
            "교육 전 검사 시작일",
            "교육 전 검사 마감일",
            "교육 후 검사 시작일",
            "교육 후 검사 마감일",
            "현재 참여자에게 열 검사",
        ):
            self.assertIn(label, source)
        self.assertIn("56 <= post_delay_days <= 70", source)
        self.assertIn("activate_assessment_phase", source)

    def test_assessment_uses_same_eight_week_instruction_for_both_phases(self) -> None:
        source = (ROOT / "pages" / "2_assessment.py").read_text(encoding="utf-8")
        self.assertIn("사전·사후 모두 동일하게 최근 8주", source)
        self.assertIn("<span>최근 8주</span>", source)
        self.assertNotIn("최근 4주", source)
        self.assertIn("sync_assessment_phase", source)

    def test_completed_post_items_open_transfer_environment_form(self) -> None:
        questions = questions_for_factors(["CORE-CO"])
        responses = {str(row["question_code"]): 3 for row in questions}
        app = AppTest.from_file(str(ROOT / "pages" / "2_assessment.py"), default_timeout=30).run()
        app.session_state["selected_factors"] = ["CORE-CO"]
        app.session_state["assessment_phase"] = "post"
        app.session_state["responses_by_phase"] = {"pre": {}, "post": responses}
        app.session_state["assessment_completed_by_phase"] = {"pre": False, "post": False}
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
        next(button for button in app.button if button.label == "저장하고 다음").click()
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertEqual(1, app.session_state["current_question"])
        self.assertEqual(1, app.session_state["current_question_by_phase"]["pre"])
        self.assertEqual(3, app.session_state["responses_by_phase"]["pre"][first_code])


if __name__ == "__main__":
    unittest.main()
