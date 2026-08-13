import unittest

from tap.scoring import (
    compare_pre_post,
    required_valid_items,
    response_quality_flags,
    response_to_index,
    score_responses,
    score_pre_post_responses,
)


QUESTIONS = [
    {"question_code": f"Q{i}", "factor_code": "F1", "factor_name_ko": "테스트", "module_group": "공통기반"}
    for i in range(1, 5)
]


class ScoringTests(unittest.TestCase):
    def test_response_conversion(self):
        self.assertEqual(response_to_index(1), 0)
        self.assertEqual(response_to_index(3), 50)
        self.assertEqual(response_to_index(5), 100)
        self.assertIsNone(response_to_index(0))

    def test_three_valid_items_are_scored(self):
        result = score_responses(QUESTIONS, {"Q1": 5, "Q2": 4, "Q3": 3, "Q4": 0})[0]
        self.assertEqual(result["status"], "산출")
        self.assertEqual(result["score_1_to_5"], 4.0)
        self.assertEqual(result["index_100"], 75.0)

    def test_two_valid_items_are_not_scored(self):
        result = score_responses(QUESTIONS, {"Q1": 5, "Q2": 4, "Q3": 0, "Q4": 0})[0]
        self.assertEqual(result["status"], "미산출")
        self.assertIsNone(result["score_1_to_5"])

    def test_missing_response_is_not_counted_as_no_opportunity(self):
        result = score_responses(QUESTIONS, {"Q1": 5, "Q2": 4, "Q3": 3})[0]
        self.assertEqual(result["status"], "산출")
        self.assertEqual(result["na_items"], 0)
        self.assertEqual(result["missing_items"], 1)

    def test_required_valid_items(self):
        self.assertEqual(required_valid_items(4), 3)
        self.assertEqual(required_valid_items(5), 4)

    def test_quality_flags_do_not_invalidate(self):
        flags = response_quality_flags({f"Q{i}": 5 for i in range(20)}, duration_seconds=20)
        self.assertIn("응답 속도 확인 필요", flags)
        self.assertIn("동일응답 반복 확인 필요", flags)

    def test_pre_post_is_named_self_report_change(self):
        rows = compare_pre_post(
            [{"factor_code": "F1", "score_1_to_5": 3.0}],
            [{"factor_code": "F1", "score_1_to_5": 3.5}],
        )
        self.assertEqual(rows[0]["self_reported_change"], 0.5)

    def test_pre_post_responses_use_same_item_intersection(self):
        rows = score_pre_post_responses(
            QUESTIONS,
            {"Q1": 1, "Q2": 4, "Q3": 4, "Q4": 0},
            {"Q1": 3, "Q2": 5, "Q3": 5, "Q4": 5},
        )
        result = rows[0]
        self.assertEqual(result["paired_valid_items"], 3)
        self.assertEqual(result["pre_score"], 3.0)
        self.assertEqual(result["post_score"], 4.33)
        self.assertEqual(result["self_reported_change"], 1.33)
        self.assertEqual(result["pre_na_items"], 1)
        self.assertEqual(result["comparison_basis"], "동일 문항 교집합")

    def test_pre_post_responses_do_not_treat_missing_or_na_as_scores(self):
        result = score_pre_post_responses(
            QUESTIONS,
            {"Q1": 3, "Q2": 4, "Q3": 0},
            {"Q1": 4, "Q2": 5, "Q3": 4, "Q4": 4},
        )[0]
        self.assertEqual(result["paired_valid_items"], 2)
        self.assertEqual(result["pre_na_items"], 1)
        self.assertEqual(result["pre_missing_items"], 1)
        self.assertEqual(result["status"], "미산출")
        self.assertIsNone(result["self_reported_change"])

    def test_score_result_can_be_tagged_with_phase(self):
        result = score_responses(
            QUESTIONS,
            {"Q1": 3, "Q2": 3, "Q3": 3, "Q4": 3},
            assessment_phase="post",
        )[0]
        self.assertEqual(result["assessment_phase"], "post")


if __name__ == "__main__":
    unittest.main()
