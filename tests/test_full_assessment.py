from __future__ import annotations

import unittest

from tap.data import (
    load_competencies,
    load_course_map,
    load_courses,
    load_questions,
    questions_for_factors,
)
from tap.recommendation import rank_courses
from tap.scoring import score_responses
from tap.selection import applicable_to_level, sanitize_selection


class FullAssessmentTests(unittest.TestCase):
    def test_every_active_item_and_factor_scores_across_response_scale(self) -> None:
        competencies = [row for row in load_competencies() if row["active_for_scoring"]]
        factor_codes = [str(row["factor_code"]) for row in competencies]
        questions = questions_for_factors(factor_codes)

        self.assertEqual(len(competencies), 31)
        self.assertEqual(len(questions), 124)

        for response_value in range(1, 6):
            responses = {str(row["question_code"]): response_value for row in questions}
            results = score_responses(questions, responses)
            self.assertEqual(len(results), 31)
            self.assertTrue(all(row["status"] == "산출" for row in results))
            self.assertTrue(all(row["score_1_to_5"] == response_value for row in results))
            self.assertTrue(all(row["missing_items"] == 0 for row in results))

    def test_every_target_level_has_a_complete_scoring_route(self) -> None:
        competencies = load_competencies()
        for target_level in ("staff", "manager", "executive"):
            expected = [
                str(row["factor_code"])
                for row in competencies
                if row["active_for_scoring"]
                and row["default_selected"]
                and applicable_to_level(row, target_level)
            ]
            selected = sanitize_selection(expected, competencies, target_level)
            questions = questions_for_factors(selected)
            responses = {
                str(row["question_code"]): 1 + (index % 5)
                for index, row in enumerate(questions)
            }
            results = score_responses(questions, responses)
            self.assertEqual({row["factor_code"] for row in results}, set(selected))
            self.assertTrue(all(row["status"] == "산출" for row in results))

    def test_all_active_factors_reach_course_ranking_without_error(self) -> None:
        factor_codes = [
            str(row["factor_code"])
            for row in load_competencies()
            if row["active_for_scoring"]
        ]
        questions = questions_for_factors(factor_codes)
        low_responses = {str(row["question_code"]): 1 for row in questions}
        results = score_responses(questions, low_responses)
        ranked = rank_courses(
            results,
            load_courses(),
            load_course_map(),
            target_level="staff",
            training_cause="knowledge_skill",
            limit=999,
        )
        self.assertGreater(len(ranked), 0)
        self.assertTrue(all(row["recommendation_score"] >= 0 for row in ranked))


if __name__ == "__main__":
    unittest.main()
