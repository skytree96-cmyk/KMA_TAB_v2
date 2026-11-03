from __future__ import annotations

import unittest

from tap.account_insights import organization_detail_rows, recommend_courses, summarize_transfer, transfer_notes


def _result(opportunity: int, barriers: list[str], *, post_completed: bool = True, applied: str = "") -> dict:
    transfer = {"application_opportunity": opportunity, "supervisor_support": 2,
                "resources_authority": 4, "time_process_support": 3, "barriers": barriers, "applied_content": applied}
    return {"post_completed": post_completed, "post_payload": {"post_transfer_responses": transfer}}


class TransferSummaryTests(unittest.TestCase):
    def test_hides_everything_below_five_complete_respondents(self):
        results = [_result(4, ["적용 기회 부족"]) for _ in range(4)]
        results.append(_result(4, [], post_completed=False))
        summary = summarize_transfer(results)
        self.assertEqual(summary["n"], 4)
        self.assertFalse(summary["disclosed"])
        self.assertTrue(all(row["mean"] is None for row in summary["factors"]))
        self.assertEqual(summary["barriers"], [])
        self.assertEqual(transfer_notes(summary), [])

    def test_averages_complete_answers_and_counts_barriers(self):
        results = [_result(score, ["상사·동료 지원 부족"] if score < 4 else ["특별한 방해요인 없음"], applied="개인 사례")
                   for score in (2, 3, 4, 5, 5)]
        incomplete = _result(1, [])
        del incomplete["post_payload"]["post_transfer_responses"]["supervisor_support"]
        summary = summarize_transfer(results + [incomplete])
        self.assertTrue(summary["disclosed"])
        self.assertEqual(summary["n"], 5)
        means = {row["code"]: row["mean"] for row in summary["factors"]}
        self.assertEqual(means["application_opportunity"], 3.8)
        self.assertEqual(means["supervisor_support"], 2.0)
        barrier = next(row for row in summary["barriers"] if row["label"] == "상사·동료 지원 부족")
        self.assertEqual((barrier["count"], barrier["rate"]), (2, 40))
        notes = transfer_notes(summary)
        self.assertIn("상사·리더 지원", notes[0])
        self.assertIn("상사·동료 지원 부족", notes[-1])
        self.assertNotIn("개인 사례", str(summary))


class CourseRecommendationTests(unittest.TestCase):
    config = {"target_means": {"CORE-CO": 3.5, "CORE-CL": 3.5}, "target_level": "manager",
              "delivery_preference": "all", "organization_priorities": ["CORE-CL"]}

    def test_recommends_only_for_competencies_below_target_without_duplicates(self):
        rows = [{"factor_code": "CORE-CO", "factor_name_ko": "소통", "post_score": 2.4},
                {"factor_code": "CORE-CL", "factor_name_ko": "협업", "post_score": 4.5},
                {"factor_code": "CORE-PS", "factor_name_ko": "미산출", "post_score": None}]
        courses = recommend_courses(self.config, rows)
        self.assertTrue(courses)
        self.assertEqual({row["factor_code"] for row in courses}, {"CORE-CO"})
        self.assertEqual(len({row["course_id"] for row in courses}), len(courses))
        self.assertTrue(all(row["delivery_label"] in {"온라인", "집합"} for row in courses))

    def test_no_courses_when_every_competency_meets_target(self):
        rows = [{"factor_code": "CORE-CO", "factor_name_ko": "소통", "post_score": 3.9}]
        self.assertEqual(recommend_courses(self.config, rows), [])


class DetailRowsTests(unittest.TestCase):
    def test_detail_rows_cover_competencies_transfer_and_barriers(self):
        summaries = [{"factor_code": "CORE-CO", "factor_name_ko": "소통", "pre_n": 6, "post_n": 5, "paired_n": 5,
                      "attrition_n": 1, "pre_mean": 3.0, "post_mean": 3.2, "observed_change": 0.2, "status": "공개"},
                     {"factor_code": "CORE-CL", "factor_name_ko": "협업", "pre_n": 3, "post_n": 3, "paired_n": 3,
                      "attrition_n": 0, "pre_mean": None, "post_mean": None, "observed_change": None, "status": "비공개(전·후 유효응답 N<5)"}]
        transfer = summarize_transfer([_result(4, ["적용 기회 부족"]) for _ in range(5)])
        rows = organization_detail_rows(summaries, {"target_means": {"CORE-CO": 3.5, "CORE-CL": 3.5}}, transfer)
        self.assertEqual([row["구분"] for row in rows].count("역량"), 2)
        self.assertEqual(rows[0]["목표 대비"], -0.3)
        self.assertIsNone(rows[1]["목표 대비"])
        self.assertEqual(sum(row["구분"] == "현업전이 환경(1~5)" for row in rows), 4)
        self.assertEqual(sum(row["구분"] == "적용 장애요인" for row in rows), 5)

    def test_undisclosed_transfer_adds_no_barrier_rows(self):
        transfer = summarize_transfer([_result(4, ["적용 기회 부족"])])
        rows = organization_detail_rows([], {}, transfer)
        self.assertTrue(all(row["평균"] is None and row["상태"].startswith("비공개") for row in rows))
        self.assertFalse(any(row["구분"] == "적용 장애요인" for row in rows))


if __name__ == "__main__":
    unittest.main()
