from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from tap.account_demand import company_demand, demand_courses, demand_csv
from tap.account_insights import environment_holds, hold_note, recommend_courses, weak_environment
from tap.data import questions_for_factors


FACTORS = ["CORE-CO", "CORE-CL"]
QUESTIONS = questions_for_factors(FACTORS)
CONFIG = {"selected_factors": FACTORS, "question_snapshot": QUESTIONS, "target_means": {"CORE-CO": 3.5, "CORE-CL": 3.5}}
NOW = datetime(2026, 11, 6, tzinfo=timezone.utc).timestamp()


def answers(levels: dict[str, int]) -> dict[str, int]:
    return {q["question_code"]: levels[q["factor_code"]] for q in QUESTIONS}


def person(uid, team, pre, post=None, *, interests=(), days_ago=10, config=CONFIG):
    row = {"id": f"a{uid}", "user_id": f"u{uid}", "department": team, "config": config,
           "pre_payload": {"responses": answers(pre), "learning_interests": list(interests)},
           "pre_completed_at": NOW - (days_ago + 30) * 86400, "post_payload": None, "post_completed_at": None}
    if post is not None:
        row["post_payload"] = {"responses": answers(post)}
        row["post_completed_at"] = NOW - days_ago * 86400
    return row


class CompanyDemandTests(unittest.TestCase):
    def test_each_person_counts_once_with_their_latest_test(self):
        rows = [person(i, "영업팀", {"CORE-CO": 2, "CORE-CL": 4}, {"CORE-CO": 3, "CORE-CL": 4}, interests=["CORE-CO"]) for i in range(5)]
        # An older project of person 0, where they still needed both: the newer post test wins.
        old = person(0, "영업팀", {"CORE-CO": 1, "CORE-CL": 1}, days_ago=200)
        old["id"] = "old"
        demand = company_demand(rows + [old], now=NOW)
        self.assertEqual(demand["people"], 5)
        by = {row["factor_code"]: row for row in demand["competencies"]}
        self.assertEqual((by["CORE-CO"]["n"], by["CORE-CO"]["need"], by["CORE-CO"]["share"], by["CORE-CO"]["interest"]), (5, 5, 100, 5))
        self.assertEqual((by["CORE-CL"]["need"], by["CORE-CL"]["interest"]), (0, 0))
        self.assertEqual(demand["competencies"][0]["factor_code"], "CORE-CO")  # highest share first

    def test_tests_older_than_a_year_and_small_groups_stay_out(self):
        rows = [person(i, "영업팀", {"CORE-CO": 2, "CORE-CL": 2}) for i in range(4)]
        rows.append(person(9, "영업팀", {"CORE-CO": 2, "CORE-CL": 2}, days_ago=400))
        demand = company_demand(rows, now=NOW)
        self.assertEqual(demand["people"], 4)
        self.assertTrue(all(not row["shown"] and row["need"] is None for row in demand["competencies"]))

    def test_departments_under_five_are_hidden_with_the_smallest_neighbour(self):
        rows = ([person(i, "영업팀", {"CORE-CO": 2, "CORE-CL": 4}) for i in range(6)]
                + [person(10 + i, "기획팀", {"CORE-CO": 4, "CORE-CL": 4}) for i in range(5)]
                + [person(20 + i, "품질팀", {"CORE-CO": 2, "CORE-CL": 4}) for i in range(3)])
        demand = company_demand(rows, now=NOW)
        cells = next(row for row in demand["grid"] if row["factor_code"] == "CORE-CO")["cells"]
        self.assertIsNone(cells["품질팀"]["share"])
        self.assertIsNone(cells["기획팀"]["share"])  # smallest shown, hidden so 품질팀 cannot be worked out
        self.assertEqual(cells["영업팀"]["share"], 100)
        csv_text = demand_csv(demand).decode("utf-8-sig")
        self.assertIn("영업팀 수요 비율(%)", csv_text)
        self.assertNotIn("u1", csv_text)

    def test_courses_for_the_most_needed_competencies_carry_the_demand_as_reason(self):
        rows = [person(i, "영업팀", {"CORE-CO": 2, "CORE-CL": 4}, interests=["CORE-CO"]) for i in range(5)]
        courses = demand_courses(company_demand(rows, now=NOW))
        self.assertTrue(courses)
        self.assertEqual({course["factor_code"] for course in courses}, {"CORE-CO"})
        self.assertEqual(courses[0]["reason"], "수요 5명(100%) · 학습 희망 5명")


class InterestAndHoldTests(unittest.TestCase):
    rows = [
        {"factor_code": "CORE-CO", "factor_name_ko": "고객지향", "pre_score": 2.5, "post_score": 2.6},
        {"factor_code": "CORE-CL", "factor_name_ko": "협업과 팀워크", "pre_score": 2.0, "post_score": 2.4},
    ]
    config = {"target_means": {"CORE-CO": 3.5, "CORE-CL": 3.5}, "target_level": "all", "delivery_preference": "all"}

    def test_own_wish_comes_first_and_is_named(self):
        plain = recommend_courses(self.config, self.rows, limit=6, today=date(2026, 11, 6), session_starts={})
        wished = recommend_courses(self.config, self.rows, limit=6, today=date(2026, 11, 6), session_starts={},
                                   interests={"CORE-CL": 1})
        self.assertEqual(plain[0]["factor_code"], "CORE-CL")  # larger gap first anyway
        self.assertEqual(wished[0]["factor_code"], "CORE-CL")
        wished_co = recommend_courses(self.config, self.rows, limit=6, today=date(2026, 11, 6), session_starts={},
                                      interests={"CORE-CO": 1})
        self.assertEqual(wished_co[0]["factor_code"], "CORE-CO")
        self.assertIn("학습 희망", wished_co[0]["reason"])
        self.assertNotIn("명", wished_co[0]["reason"].split("학습 희망")[1])

    def test_organization_reason_counts_the_wishes_and_names_priorities(self):
        config = {**self.config, "organization_priorities": ["CORE-CO"]}
        courses = recommend_courses(config, self.rows, limit=9, audience="organization", today=date(2026, 11, 6),
                                    session_starts={}, interests={"CORE-CO": 7})
        co = next(course for course in courses if course["factor_code"] == "CORE-CO")
        self.assertIn("조직 우선역량", co["reason"])
        self.assertIn("학습 희망 7명", co["reason"])

    def test_no_change_and_a_weak_environment_hold_the_course(self):
        self.assertEqual(weak_environment({"resources_authority": 2, "time_process_support": 4}), ["도구·정보·권한"])
        summary = {"disclosed": True, "factors": [{"code": "resources_authority", "mean": 3.4},
                                                   {"code": "time_process_support", "mean": 2.8}]}
        self.assertEqual(weak_environment(summary), ["시간·프로세스"])
        self.assertEqual(weak_environment({**summary, "disclosed": False}), [])
        held = environment_holds(self.config, self.rows, ["도구·정보·권한"])
        self.assertEqual([item["factor_code"] for item in held], ["CORE-CO"])  # CORE-CL rose 0.4, so it keeps its course
        self.assertEqual(hold_note(held[0]), "목표보다 0.90점 낮고 교육 전보다 0.10점 오르는 데 그쳤습니다. "
                                             "도구·정보·권한 응답이 낮아 과정보다 업무 환경을 먼저 점검하세요.")
        self.assertEqual(environment_holds(self.config, self.rows, []), [])
        courses = recommend_courses(self.config, self.rows, limit=6, today=date(2026, 11, 6), session_starts={},
                                    hold={"CORE-CO"})
        self.assertNotIn("CORE-CO", {course["factor_code"] for course in courses})


if __name__ == "__main__":
    unittest.main()
