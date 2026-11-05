from __future__ import annotations

from datetime import date
import unittest
from unittest.mock import patch

from tap.account_insights import (course_context_note, course_gap_counts, course_topic_words, team_heatmap, organization_detail_rows, recommend_courses,
                                  summarize_transfer, transfer_notes)
from tap.data import load_courses


def _course(course_id: str, title: str, source: str = "public_edu_center", starts: str = "", **extra: object) -> dict:
    row = {"course_id": course_id, "title": title, "source": source, "target_level": "all", "active": True,
           "delivery": {"public_edu_center": "offline", "studio_elearning": "online"}.get(source, "inhouse")}
    if starts:
        row.update(next_start=starts.split("|")[0], upcoming_starts=starts)
    return {**row, **extra}


def _catalog(courses: list[dict], mapping: list[tuple[str, str, float]]):
    """Swap the KMA catalog for a few hand-made rows while the block runs."""
    rows = [{"factor_code": code, "course_id": course_id, "content_fit": fit} for code, course_id, fit in mapping]
    return patch.multiple("tap.account_insights", load_courses=lambda: courses, load_course_map=lambda: rows)


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
        self.assertTrue(all(row["delivery_label"] in {"온라인", "집합", "온라인 라이브"} for row in courses))
        # individuals see public courses and e-learning only; the in-house inquiry course is for organizations
        self.assertEqual([row["source"] for row in courses[:2]], ["public_edu_center", "studio_elearning"])
        self.assertTrue(all(row["source"] != "b2b_inquiry" for row in courses))
        self.assertTrue(all(row["schedule"] for row in courses))

    def test_no_courses_when_every_competency_meets_target(self):
        rows = [{"factor_code": "CORE-CO", "factor_name_ko": "소통", "post_score": 3.9}]
        self.assertEqual(recommend_courses(self.config, rows), [])

    def test_gap_counts_tell_why_a_course_list_is_empty(self):
        config = {"target_means": {"A": 3.5, "B": 3.5}}
        self.assertEqual(course_gap_counts(config, [{"factor_code": "A", "post_score": None}]), (0, 0))
        self.assertEqual(course_gap_counts(config, [{"factor_code": "A", "post_score": 3.4}]), (1, 0))
        self.assertEqual(course_gap_counts(config, [{"factor_code": "A", "post_score": 3.3},
                                                     {"factor_code": "B", "post_score": 2.0}]), (2, 2))
        self.assertEqual(course_gap_counts(config, [{"factor_code": "A", "score_1_to_5": 2.0}], "score_1_to_5"), (1, 1))

    def test_team_heatmap_hides_small_cells_and_the_cell_that_would_reveal_them(self):
        def team(name, n, post=3.5):
            return {"team": name, "paired_n": n, "summaries": [
                {"factor_code": "A", "factor_name_ko": "고객지향", "paired_n": n,
                 "post_mean": post if n >= 5 else None, "observed_change": 0.3 if n >= 5 else None}]}
        grid = team_heatmap([team("영업팀", 9, 4.0), team("개발팀", 6), team("품질팀", 3), team("빈팀", 0)])
        self.assertEqual([row["team"] for row in grid["rows"]], ["영업팀", "개발팀", "품질팀"])
        cells = {row["team"]: row["cells"][0] for row in grid["rows"]}
        self.assertEqual(cells["영업팀"]["post_mean"], 4.0)
        self.assertFalse(cells["품질팀"]["shown"])
        # 품질팀 alone hidden would be total minus the others, so the smallest shown team is hidden too.
        self.assertFalse(cells["개발팀"]["shown"])
        self.assertIsNone(cells["개발팀"]["post_mean"])
        both_shown = team_heatmap([team("영업팀", 9), team("개발팀", 6)])
        self.assertTrue(all(row["cells"][0]["shown"] for row in both_shown["rows"]))

    def test_courses_for_another_level_are_never_offered(self):
        rows = [{"factor_code": "JOB-EX", "factor_name_ko": "실행력", "post_score": 2.0},
                {"factor_code": "FIN_CORE", "factor_name_ko": "재무", "post_score": 2.0}]

        def levels(target_level):
            config = {**self.config, "target_level": target_level}
            return {row["target_level"] for row in recommend_courses(config, rows, limit=10)}

        self.assertTrue(levels("staff") <= {"all", "staff"})
        self.assertTrue(levels("manager") <= {"all", "manager"})
        self.assertNotIn("executive", levels("staff") | levels("manager"))

    def test_gap_within_report_noise_band_recommends_nothing(self):
        rows = [{"factor_code": "CORE-CO", "factor_name_ko": "고객지향", "post_score": 3.35}]
        self.assertEqual(recommend_courses(self.config, rows), [])
        rows[0]["post_score"] = 3.3
        self.assertEqual({row["factor_code"] for row in recommend_courses(self.config, rows)}, {"CORE-CO"})

    def test_larger_gap_first_and_every_competency_before_second_courses(self):
        rows = [{"factor_code": "CORE-CO", "factor_name_ko": "고객지향", "post_score": 3.0},
                {"factor_code": "JOB-PS", "factor_name_ko": "문제해결력", "post_score": 2.5}]
        courses = recommend_courses({**self.config, "organization_priorities": []}, rows)
        # public courses for every competency first, then e-learning for every competency
        self.assertEqual([row["factor_code"] for row in courses], ["JOB-PS", "CORE-CO", "JOB-PS", "CORE-CO"])
        self.assertEqual([row["source"] for row in courses],
                         ["public_edu_center", "public_edu_center", "studio_elearning", "studio_elearning"])
        rows[1]["pre_score"] = 2.5
        advice = [row["advice"] for row in recommend_courses({**self.config, "organization_priorities": []}, rows)]
        self.assertTrue(advice[0])
        self.assertEqual(advice[2], "")

    def test_same_course_at_another_location_or_year_is_not_repeated(self):
        from tap.recommendation import normalize_course_title
        rows = [{"factor_code": "LEAD-PD", "factor_name_ko": "사람 육성", "post_score": 2.0}]
        courses = recommend_courses({**self.config, "organization_priorities": []}, rows, limit=10)
        keys = [normalize_course_title(row["title"]) for row in courses]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(row.get("has_upcoming", True) for row in courses if row["source"] == "public_edu_center"))

    def test_organizations_also_get_an_inhouse_inquiry_course(self):
        rows = [{"factor_code": "JOB-PS", "factor_name_ko": "문제해결력", "post_score": 2.5}]
        courses = recommend_courses({**self.config, "organization_priorities": []}, rows, limit=9, audience="organization")
        self.assertEqual([row["source"] for row in courses[:3]], ["public_edu_center", "studio_elearning", "b2b_inquiry"])

    def test_only_the_three_largest_gaps_get_courses(self):
        rows = [{"factor_code": code, "factor_name_ko": code, "post_score": 2.0 + index * 0.1}
                for index, code in enumerate(("LEAD-PD", "JOB-PS", "CORE-CL", "DATA_ANA", "AI_USE"))]
        courses = recommend_courses({**self.config, "organization_priorities": []}, rows, limit=6)
        self.assertEqual({row["factor_code"] for row in courses}, {"LEAD-PD", "JOB-PS", "CORE-CL"})
        self.assertEqual([row["source"] for row in courses],
                         ["public_edu_center"] * 3 + ["studio_elearning"] * 3)

    def test_pre_training_report_uses_the_pre_score(self):
        rows = [{"factor_code": "JOB-PS", "factor_name_ko": "문제해결력", "score_1_to_5": 2.5, "status": "산출"}]
        courses = recommend_courses(self.config, rows, score_key="score_1_to_5")
        self.assertTrue(courses)
        self.assertTrue(courses[0]["reason"].startswith("교육 전 2.50점"))
        self.assertEqual(courses[0]["advice"], "")

    def test_organization_priority_breaks_ties_within_the_same_gap_band(self):
        # 0.50 and 0.48 share the 0.5 band; without the priority CORE-CL would sort first by code.
        rows = [{"factor_code": "CORE-CL", "factor_name_ko": "협업", "post_score": 3.0},
                {"factor_code": "CORE-CO", "factor_name_ko": "고객지향", "post_score": 3.02}]
        self.assertEqual(recommend_courses({**self.config, "organization_priorities": []}, rows, limit=1)[0]["factor_code"], "CORE-CL")
        self.assertEqual(recommend_courses({**self.config, "organization_priorities": ["CORE-CO"]}, rows, limit=1)[0]["factor_code"], "CORE-CO")

    def test_delivery_preference_orders_courses_within_a_competency(self):
        rows = [{"factor_code": "JOB-PS", "factor_name_ko": "문제해결력", "post_score": 2.5}]
        first = recommend_courses({**self.config, "delivery_preference": "online"}, rows, limit=1)[0]
        self.assertEqual(first["delivery"], "online")

    def test_reason_and_advice_follow_the_pre_post_change(self):
        def advice(pre):
            row = {"factor_code": "CORE-CO", "factor_name_ko": "고객지향", "pre_score": pre, "post_score": 3.0}
            return recommend_courses(self.config, [row])[0]

        rising = advice(2.4)
        self.assertEqual(rising["reason"], "교육 후 3.00점, 목표 3.50점보다 0.50점 낮음 · 교육 전보다 0.60점 높음")
        self.assertTrue(advice(3.4)["reason"].endswith("교육 전보다 0.40점 낮음"))
        # A zero change is said in words, never as a signed "+0.00점".
        self.assertTrue(advice(3.0)["reason"].endswith("교육 전과 같음"))
        self.assertIn("심화", rising["advice"])
        self.assertIn("큰 차이가 없습니다", advice(3.1)["advice"])
        self.assertIn("낮아졌습니다", advice(3.4)["advice"])
        self.assertEqual(advice(None)["advice"], "")

    def test_training_that_cannot_fix_the_cause_recommends_nothing(self):
        rows = [{"factor_code": "CORE-CO", "factor_name_ko": "고객지향", "post_score": 2.0}]
        self.assertEqual(recommend_courses({**self.config, "training_cause": "system_only"}, rows), [])

    def test_weak_transfer_conditions_come_before_the_course_list(self):
        weak = summarize_transfer([_result(4, []) for _ in range(5)])
        note = course_context_note(weak)
        self.assertIn("상사·리더 지원", note)
        self.assertNotIn("적용 기회", note)
        self.assertIsNone(course_context_note(summarize_transfer([_result(4, [])])))
        self.assertIsNone(course_context_note(None))

    def test_parts_of_one_series_count_as_the_same_course(self):
        from tap.recommendation import normalize_course_title
        self.assertEqual(normalize_course_title("[HD]직장인을 위한 AI 활용 실무 Part.1 ChatGPT 엑셀, 파워포인트, VBA"),
                         normalize_course_title("[HD]직장인을 위한 AI 활용 실무 Part.2 ChatGPT Google Docs, 업무용 글쓰기 등"))
        self.assertEqual(normalize_course_title("빅데이터 분석 - Pandas 실전 강의 Part.1-1 개발환경설치 및 소개"),
                         normalize_course_title("빅데이터 분석 - Pandas 실전 강의 Part.1-2 DataFrame"))
        self.assertEqual(normalize_course_title("멘토링 바이블 1편"), normalize_course_title("멘토링 바이블 2편"))
        self.assertNotEqual(normalize_course_title("코칭 대화법 1편"), normalize_course_title("코칭 리더십 1편"))
        # A title that starts with a number is not a series tail.
        self.assertEqual(normalize_course_title("4차 산업혁명 시대의 리더십"), "4차산업혁명시대의리더십")

    def test_sessions_starting_within_a_week_are_skipped(self):
        courses = [_course("SOON", "[여의도] 고객 경험 설계", starts="20261104|20261201"),
                   _course("ONLY-SOON", "[여의도] 고객 불만 응대", starts="20261106"),
                   _course("LATER", "[여의도] 고객 여정 분석", starts="20261120")]
        rows = [{"factor_code": "CORE-CO", "factor_name_ko": "고객지향", "post_score": 2.0}]
        with _catalog(courses, [("CORE-CO", c["course_id"], 0.9) for c in courses]):
            picked = recommend_courses(self.config, rows, limit=5, today=date(2026, 11, 4))
        # LATER's only session (11-20) is sooner than SOON's first joinable one (12-01); ONLY-SOON cannot be joined.
        self.assertEqual([row["course_id"] for row in picked], ["LATER", "SOON"])
        self.assertEqual(picked[1]["schedule"], "다음 개강 2026-12-01")

    def test_equal_fit_prefers_a_new_subject_within_a_competency(self):
        courses = [_course("PUB", "[비대면] 일잘러라면 꼭 알아야 하는 노션 활용법", starts="20261211", delivery="online_live"),
                   _course("EL-A", "[HD]일과 생활을 편하게 관리하는 Notion(노션) 활용 Part.1 기본 1", "studio_elearning"),
                   _course("EL-B", "[리더십 아카이브] 변화 리더십(조직개발과 퍼실리테이션)", "studio_elearning"),
                   _course("EL-C", "Claude를 활용한 업무자동화", "studio_elearning")]
        mapping = [("DX_APPLY", "PUB", 0.8), ("DX_APPLY", "EL-A", 0.8), ("DX_APPLY", "EL-B", 0.7), ("DX_APPLY", "EL-C", 0.8)]
        rows = [{"factor_code": "DX_APPLY", "factor_name_ko": "디지털 혁신 적용", "post_score": 2.0}]
        with _catalog(courses, mapping):
            picked = recommend_courses(self.config, rows, limit=3, today=date(2026, 11, 4))
        # EL-A fits as well as EL-C but repeats the Notion subject; the lower-fitting EL-B never jumps ahead.
        self.assertEqual([row["course_id"] for row in picked], ["PUB", "EL-C", "EL-A"])
        self.assertEqual(course_topic_words("Claude를 활용한 업무자동화"), {"claude", "업무자동화"})
        self.assertIn("노션", course_topic_words("[HD]일과 생활을 편하게 관리하는 Notion(노션) 활용 Part.1 기본 1"))

    def test_competency_without_the_preferred_source_keeps_its_place(self):
        courses = [_course("SALES-PUB", "[여의도] 세일즈 협상 스킬", starts="20261127"),
                   _course("SALES-PUB2", "[여의도] 영업사원을 위한 손익관리", starts="20261130"),
                   _course("PRES-EL", "OK를 부르는 프레젠테이션 스킬", "studio_elearning"),
                   _course("PRES-PUB", "[여의도] 보이스 트레이닝", starts="20261112")]
        mapping = [("SALES_CORE", "SALES-PUB", 0.95), ("SALES_CORE", "SALES-PUB2", 0.85),
                   ("COMM_PRES", "PRES-EL", 0.9), ("COMM_PRES", "PRES-PUB", 0.9)]
        rows = [{"factor_code": "SALES_CORE", "factor_name_ko": "영업 핵심역량", "post_score": 2.0},
                {"factor_code": "COMM_PRES", "factor_name_ko": "설득·프레젠테이션", "post_score": 2.5}]
        config = {**self.config, "target_level": "staff", "delivery_preference": "online", "organization_priorities": []}
        with _catalog(courses, mapping):
            picked = recommend_courses(config, rows, limit=4, today=date(2026, 11, 4))
        # Sales has no e-learning, so it takes its public course in the first round instead of dropping to third.
        self.assertEqual([row["course_id"] for row in picked], ["SALES-PUB", "PRES-EL", "SALES-PUB2", "PRES-PUB"])

    def test_course_links_use_current_kma_paths(self):
        urls = {row["url"] for row in load_courses()}
        self.assertTrue(urls)
        self.assertTrue(all(url.startswith(("https://www.kma.or.kr/", "https://studio.kma.or.kr/")) for url in urls),
                        [url for url in urls if not url.startswith(("https://www.kma.or.kr/", "https://studio.kma.or.kr/"))][:5])


class DetailRowsTests(unittest.TestCase):
    def test_detail_rows_cover_competencies_transfer_and_barriers(self):
        summaries = [{"factor_code": "CORE-CO", "factor_name_ko": "소통", "pre_n": 6, "post_n": 5, "paired_n": 5,
                      "attrition_n": 1, "pre_mean": 3.0, "post_mean": 3.2, "observed_change": 0.2, "status": "공개"},
                     {"factor_code": "CORE-CL", "factor_name_ko": "협업", "pre_n": 3, "post_n": 3, "paired_n": 3,
                      "attrition_n": 0, "pre_mean": None, "post_mean": None, "observed_change": None, "status": "비공개(교육 전후 유효응답 N<5)"}]
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
