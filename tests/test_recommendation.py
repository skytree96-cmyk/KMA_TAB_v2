import unittest
from pathlib import Path

from tap.recommendation import (
    ORGANIZATION_SLOTS,
    normalize_course_title,
    rank_courses,
    recommend_for_factors,
    recommendation_score,
)


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

    def _catalog(self):
        courses = [
            {"course_id": "OFF-A", "title": "[여의도] 리더의 피드백 스킬", "source": "public_edu_center", "active": True, "target_level": "all", "delivery": "offline", "next_start": "20261201"},
            {"course_id": "OFF-A2", "title": "[부산] 리더의 피드백 스킬", "source": "public_edu_center", "active": True, "target_level": "all", "delivery": "offline", "next_start": "20270115"},
            {"course_id": "OFF-B", "title": "[여의도] 코칭 대화법", "source": "public_edu_center", "active": True, "target_level": "all", "delivery": "offline", "next_start": "20261220"},
            {"course_id": "OFF-CLOSED", "title": "[여의도] 기수 없는 코칭 과정", "source": "public_edu_center", "active": False, "target_level": "all", "delivery": "offline", "next_start": ""},
            {"course_id": "LXP-A", "title": "셀프코칭 (2026)", "source": "studio_elearning", "active": True, "target_level": "all", "delivery": "online"},
            {"course_id": "B2B-A", "title": "사내 코칭 워크숍", "source": "b2b_inquiry", "active": True, "target_level": "all", "delivery": "inhouse"},
            {"course_id": "OFF-PS", "title": "[여의도] 문제해결 의사결정", "source": "public_edu_center", "active": True, "target_level": "all", "delivery": "offline", "next_start": "20261105"},
            {"course_id": "STU-A", "title": "리더의 질문", "source": "studio_original", "active": True, "target_level": "all", "delivery": "online_short"},
        ]
        mapping = [
            {"factor_code": "LEAD-PD", "course_id": "OFF-A", "content_fit": 0.95, "rationale": "r"},
            {"factor_code": "LEAD-PD", "course_id": "OFF-A2", "content_fit": 0.95, "rationale": "r"},
            {"factor_code": "LEAD-PD", "course_id": "OFF-B", "content_fit": 0.9, "rationale": "r"},
            {"factor_code": "LEAD-PD", "course_id": "OFF-CLOSED", "content_fit": 0.99, "rationale": "r"},
            {"factor_code": "LEAD-PD", "course_id": "LXP-A", "content_fit": 0.8, "rationale": "r"},
            {"factor_code": "LEAD-PD", "course_id": "B2B-A", "content_fit": 0.9, "rationale": "r"},
            {"factor_code": "LEAD-PD", "course_id": "STU-A", "content_fit": 0.6, "rationale": "r"},
            {"factor_code": "JOB-PS", "course_id": "OFF-PS", "content_fit": 0.95, "rationale": "r"},
            {"factor_code": "JOB-PS", "course_id": "OFF-A", "content_fit": 0.7, "rationale": "r"},
        ]
        results = [
            {"factor_code": "JOB-PS", "factor_name_ko": "문제해결력", "status": "산출", "gap_to_target": 0.4},
            {"factor_code": "LEAD-PD", "factor_name_ko": "사람 육성", "status": "산출", "gap_to_target": 1.2},
            {"factor_code": "CORE-CL", "factor_name_ko": "협업", "status": "산출", "gap_to_target": 0.0},
            {"factor_code": "AI_USE", "factor_name_ko": "AI", "status": "미산출", "gap_to_target": None},
        ]
        return courses, mapping, results

    def test_factor_first_ordering_and_slots(self):
        courses, mapping, results = self._catalog()
        blocks = recommend_for_factors(results, courses, mapping)
        self.assertEqual([b["factor_code"] for b in blocks], ["LEAD-PD", "JOB-PS"])
        lead = blocks[0]
        self.assertEqual([c["source"] for c in lead["courses"]], ["public_edu_center", "studio_elearning"])
        self.assertEqual(lead["courses"][0]["course_id"], "OFF-A")
        self.assertEqual([s["course_id"] for s in lead["supplements"]], ["STU-A"])
        # 교육문의형은 개인 슬롯에 없다
        self.assertNotIn("B2B-A", [c["course_id"] for c in lead["courses"]])

    def test_closed_courses_and_duplicate_titles_are_skipped(self):
        courses, mapping, results = self._catalog()
        blocks = recommend_for_factors(results, courses, mapping)
        picked = [c["course_id"] for b in blocks for c in b["courses"]]
        self.assertNotIn("OFF-CLOSED", picked)
        # 부산 기수(같은 제목)는 여의도 기수가 이미 쓰였으므로 뽑히지 않고, 문제해결력은 자기 과정을 받는다
        self.assertNotIn("OFF-A2", picked)
        self.assertEqual(blocks[1]["courses"][0]["course_id"], "OFF-PS")

    def test_organization_slots_put_priority_factor_first(self):
        courses, mapping, results = self._catalog()
        blocks = recommend_for_factors(
            results, courses, mapping,
            organization_priorities={"JOB-PS"}, priority_first=True,
            slots=ORGANIZATION_SLOTS, supplement_limit=0,
        )
        self.assertEqual(blocks[0]["factor_code"], "JOB-PS")
        lead = blocks[1]
        self.assertIn("B2B-A", [c["course_id"] for c in lead["courses"]])
        self.assertEqual(lead["supplements"], [])

    def test_system_cause_returns_no_blocks(self):
        courses, mapping, results = self._catalog()
        self.assertEqual(recommend_for_factors(results, courses, mapping, training_cause="system_only"), [])

    def test_title_normalization(self):
        self.assertEqual(normalize_course_title("[여의도] 리더의 피드백 스킬"), normalize_course_title("[부산] 리더의  피드백 스킬 (2027)"))


if __name__ == "__main__":
    unittest.main()
