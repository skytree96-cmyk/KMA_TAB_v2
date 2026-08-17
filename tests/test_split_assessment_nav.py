from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tap.data import questions_for_factors


ROOT = Path(__file__).resolve().parents[1]


class SplitAssessmentNavigationTests(unittest.TestCase):
    def _page(self, filename: str) -> AppTest:
        return AppTest.from_file(
            str(ROOT / "pages" / filename), default_timeout=30
        ).run()

    def test_pre_entry_forces_pre_and_preserves_post_responses(self) -> None:
        questions = questions_for_factors(["CORE-CO"])
        post_responses = {str(questions[0]["question_code"]): 5}
        app = self._page("7_pre_assessment.py")
        app.session_state["selected_factors"] = ["CORE-CO"]
        app.session_state["assessment_phase"] = "post"
        app.session_state["responses_by_phase"] = {
            "pre": {},
            "post": dict(post_responses),
        }
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertEqual("pre", app.session_state["assessment_phase"])
        self.assertEqual(post_responses, app.session_state["responses_by_phase"]["post"])
        self.assertTrue(any("교육 전 역량평가" in str(item.value) for item in app.markdown))

    def test_fresh_entries_show_only_the_relevant_start_flow(self) -> None:
        pre_app = self._page("7_pre_assessment.py")
        self.assertTrue(
            any("교육 전 검사 시작" in str(item.value) for item in pre_app.markdown)
        )
        self.assertFalse(
            any(
                item.label == "교육 전 검사 기준파일(JSON)"
                for item in pre_app.get("file_uploader")
            )
        )

        post_app = self._page("8_post_assessment.py")
        self.assertTrue(
            any("교육 후 검사 이어하기" in str(item.value) for item in post_app.markdown)
        )
        self.assertTrue(
            any(
                item.label == "교육 전 검사 기준파일(JSON)"
                for item in post_app.get("file_uploader")
            )
        )

    def test_post_entry_forces_post_and_requires_completed_pre(self) -> None:
        app = self._page("8_post_assessment.py")
        app.session_state["selected_factors"] = ["CORE-CO"]
        app.session_state["assessment_phase"] = "pre"
        app.session_state["assessment_completed_by_phase"] = {
            "pre": False,
            "post": False,
        }
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertEqual("post", app.session_state["assessment_phase"])
        self.assertFalse(any(item.label == "응답" for item in app.radio))
        self.assertTrue(
            any(
                item.label == "교육 전 검사 기준파일(JSON)"
                for item in app.get("file_uploader")
            )
        )

    def test_post_entry_keeps_pre_state_and_opens_post_question(self) -> None:
        questions = questions_for_factors(["CORE-CO"])
        pre_responses = {str(row["question_code"]): 3 for row in questions}
        app = self._page("8_post_assessment.py")
        app.session_state["selected_factors"] = ["CORE-CO"]
        app.session_state["participant_id"] = "EDU-SPLIT-001"
        app.session_state["assessment_phase"] = "pre"
        app.session_state["responses_by_phase"] = {
            "pre": dict(pre_responses),
            "post": {},
        }
        app.session_state["assessment_completed_by_phase"] = {
            "pre": True,
            "post": False,
        }
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertEqual("post", app.session_state["assessment_phase"])
        self.assertEqual(pre_responses, app.session_state["responses_by_phase"]["pre"])
        self.assertTrue(any(item.label == "응답" for item in app.radio))
        participant = next(
            item for item in app.text_input if item.label == "교육 참여자 ID"
        )
        self.assertEqual("EDU-SPLIT-001", participant.value)
        self.assertTrue(participant.disabled)

    def test_completed_pre_page_offers_direct_post_navigation(self) -> None:
        questions = questions_for_factors(["CORE-CO"])
        responses = {str(row["question_code"]): 3 for row in questions}
        app = self._page("7_pre_assessment.py")
        app.session_state["selected_factors"] = ["CORE-CO"]
        app.session_state["participant_id"] = "EDU-SPLIT-002"
        app.session_state["responses_by_phase"] = {"pre": responses, "post": {}}
        app.session_state["assessment_completed_by_phase"] = {
            "pre": True,
            "post": False,
        }
        app.run()

        labels = {item.label for item in app.button}
        self.assertIn("교육 전 결과 보기", labels)
        self.assertIn("교육 후 검사로 이동", labels)


if __name__ == "__main__":
    unittest.main()
