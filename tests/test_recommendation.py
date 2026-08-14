import unittest
from pathlib import Path

from tap.recommendation import rank_courses, recommendation_score


class RecommendationTests(unittest.TestCase):
    def test_maximum_base_score(self):
        parts = recommendation_score(
            gap_to_target=4,
            content_fit=1,
            organization_priority=True,
            learner_interest=True,
            level_fit=True,
            delivery_fit=True,
            training_cause="knowledge_skill",
        )
        self.assertEqual(parts["recommendation_score"], 100.0)

    def test_system_cause_suppresses_training(self):
        rows = rank_courses(
            [{"factor_code": "F", "factor_name_ko": "역량", "status": "산출", "gap_to_target": 1.0}],
            [{"course_id": "C", "active": True, "target_level": "all", "delivery": "online"}],
            [{"factor_code": "F", "course_id": "C", "content_fit": 1.0, "rationale": "직접 연계"}],
            training_cause="system_only",
        )
        self.assertEqual(rows, [])

    def test_unknown_cause_is_a_neutral_default(self):
        known = recommendation_score(
            gap_to_target=2,
            content_fit=0.8,
            organization_priority=True,
            learner_interest=False,
            level_fit=True,
            delivery_fit=True,
            training_cause="knowledge_skill",
        )
        unknown = recommendation_score(
            gap_to_target=2,
            content_fit=0.8,
            organization_priority=True,
            learner_interest=False,
            level_fit=True,
            delivery_fit=True,
            training_cause="mixed_or_unknown",
        )
        self.assertEqual(unknown["training_gate"], 1.0)
        self.assertEqual(unknown["recommendation_score"], known["recommendation_score"])

    def test_project_setup_defers_gap_cause_to_post_assessment(self):
        source = (
            Path(__file__).resolve().parents[1] / "pages" / "1_project_setup.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("현재 격차의 주된 원인", source)
        self.assertIn('training_cause = "mixed_or_unknown"', source)
        self.assertIn("격차 원인은 교육 후에 확인", source)


if __name__ == "__main__":
    unittest.main()
