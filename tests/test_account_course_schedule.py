from __future__ import annotations

from datetime import date
import os
import threading
import unittest
from unittest.mock import patch

from tap import course_schedule
from tap.account_insights import recommend_courses
from tap.course_schedule import catalog_categories, live_session_starts, parse_sessions
from tap.data import load_courses


def public_course(course_id="KMA-OFF-1", crscd="1", **extra):
    return {"course_id": course_id, "title": f"협업 과정 {crscd}", "source": "public_edu_center", "delivery": "offline",
            "target_level": "all", "crscd": crscd, "active": True, "has_upcoming": True,
            "url": f"https://www.kma.or.kr/usrs/eduRegMgnt/eduRegInfoDetailForm.do?p_edutype_cd=001&p_crscd={crscd}"
                   f"&p_crsseq_id=&p_view_type=S&p_ctgry_id=558&CRSCD={crscd}&CRSSEQ_ID=&p_hmpgcd=30&mkey=36326",
            "upcoming_starts": "20261110", "next_start": "20261110", **extra}


class SessionParsingTests(unittest.TestCase):
    def test_months_and_linked_session_are_collected_per_course(self):
        rows = [{"CRSCD": 111407, "EDU_MONTH_10": "1차@127307@2026.10.14~2026.10.15",
                 "EDU_MONTH_12": "2차@125789@2026.12.09~2026.12.10|3차@125790@2026.12.21~2026.12.22",
                 "LINK_CRSSEQ_ID": 125789, "EDU_STRTDT": "20261209"},
                {"CRSCD": 111407, "EDU_MONTH_1": "깨진값", "EDU_MONTH_2": "x@abc@2027.02.01~2027.02.02"},
                {"CRSCD": "", "EDU_MONTH_3": "1차@1@2027.03.01~2027.03.02"}]
        self.assertEqual(parse_sessions(rows), {"111407": {"20261014", "20261209", "20261221"}})

    def test_categories_come_from_the_public_course_links(self):
        courses = [public_course(), public_course("KMA-OFF-2", "2"),
                   {"source": "studio_elearning", "url": "https://studio.kma.or.kr/member/eLearning/1?p_ctgry_id=9&mkey=9"},
                   {"source": "public_edu_center", "url": "https://www.kma.or.kr/x?p_ctgry_id=&mkey=1"}]
        self.assertEqual(catalog_categories(courses), [("558", "36326")])

    def test_the_bundled_catalog_yields_categories_and_studio_thumbnails(self):
        courses = load_courses()
        self.assertGreater(len(catalog_categories(courses)), 10)
        studio = [row for row in courses if row["source"] == "studio_elearning"]
        with_thumb = [row for row in studio if row["thumb_url"]]
        self.assertGreater(len(with_thumb), len(studio) * 0.9)
        self.assertTrue(all(row["thumb_url"].startswith("https://studio.kma.or.kr/_next/image?url=") for row in with_thumb))


class LiveScheduleStateTests(unittest.TestCase):
    def setUp(self):
        course_schedule.reset_for_tests()
        self.addCleanup(course_schedule.reset_for_tests)

    def wait(self):
        for thread in threading.enumerate():
            if thread.name == "tap-course-schedule":
                thread.join(timeout=10)

    def test_off_by_default_and_never_fetches(self):
        with patch.dict(os.environ, {course_schedule.ENV_FLAG: ""}), \
                patch.object(course_schedule, "fetch_session_starts") as fetch:
            self.assertIsNone(live_session_starts())
            fetch.assert_not_called()
            self.assertIn("카탈로그", course_schedule.schedule_basis())

    def test_first_call_returns_none_then_the_refreshed_answer(self):
        answer = {str(row["crscd"]): ["20991231"] for row in load_courses() if row["source"] == "public_edu_center"}
        with patch.dict(os.environ, {course_schedule.ENV_FLAG: "1"}), \
                patch.object(course_schedule, "fetch_session_starts", return_value=answer) as fetch:
            self.assertIsNone(live_session_starts())  # the report does not wait for the fetch
            self.wait()
            self.assertEqual(live_session_starts(), answer)
            self.assertEqual(live_session_starts(), answer)
            self.assertIn("KMA 사이트에서 조회", course_schedule.schedule_basis())
            fetch.assert_called_once()

    def test_unanswered_category_keeps_its_catalog_dates_and_the_rest_goes_live(self):
        public = [row for row in load_courses() if row["source"] == "public_edu_center"]
        down = catalog_categories(public)[0]
        in_down = [row for row in public if catalog_categories([row]) == [down]]
        answer = {str(row["crscd"]): ["20991231"] for row in public if row not in in_down}

        def fetch(categories, years, *, failed=None, **_):
            failed.add(down)
            return dict(answer)

        with patch.dict(os.environ, {course_schedule.ENV_FLAG: "1"}), \
                patch.object(course_schedule, "fetch_session_starts", side_effect=fetch):
            live_session_starts()
            self.wait()
            live = live_session_starts()
        self.assertIsNotNone(live)
        sample = next(row for row in public if row not in in_down)
        self.assertEqual(live[str(sample["crscd"])], ["20991231"])
        for row in in_down:
            catalog = sorted({s for s in str(row.get("upcoming_starts") or "").split("|") if len(s) == 8})
            self.assertEqual(live[str(row["crscd"])], catalog)

    def test_failed_or_thin_answer_keeps_the_catalog_and_waits_before_retrying(self):
        for outcome in ({"side_effect": OSError("down")}, {"return_value": {"1": ["20991231"]}}):
            course_schedule.reset_for_tests()
            with self.subTest(outcome=list(outcome)), patch.dict(os.environ, {course_schedule.ENV_FLAG: "1"}), \
                    patch.object(course_schedule, "fetch_session_starts", **outcome) as fetch:
                self.assertIsNone(live_session_starts())
                self.wait()
                self.assertIsNone(live_session_starts())
                self.wait()
                fetch.assert_called_once()  # no second try inside the retry window


class LiveScheduleRecommendationTests(unittest.TestCase):
    config = {"target_means": {"CORE-CL": 3.5}, "target_level": "all", "delivery_preference": "all"}
    rows = [{"factor_code": "CORE-CL", "factor_name_ko": "협업", "post_score": 2.5}]
    mapping = [{"factor_code": "CORE-CL", "course_id": "KMA-OFF-1", "content_fit": 0.9},
               {"factor_code": "CORE-CL", "course_id": "KMA-OFF-2", "content_fit": 0.8}]

    def recommend(self, session_starts):
        courses = [public_course(), public_course("KMA-OFF-2", "2", title="팀워크 워크숍")]
        with patch("tap.account_insights.load_courses", return_value=courses), \
                patch("tap.account_insights.load_course_map", return_value=self.mapping):
            return recommend_courses(self.config, self.rows, today=date(2026, 12, 1), session_starts=session_starts)

    def test_live_dates_replace_an_aged_catalog(self):
        # Both catalog sessions (11-10) are over on 12-01, so the catalog alone offers nothing.
        with patch("tap.account_insights.live_session_starts", return_value=None):
            self.assertEqual(self.recommend(None), [])
        picked = self.recommend({"1": ["20261203", "20270114"], "2": ["20261215"]})
        self.assertEqual([(row["course_id"], row["next_start"]) for row in picked],
                         [("KMA-OFF-1", "20270114"), ("KMA-OFF-2", "20261215")])
        self.assertIn("다음 개강 2027-01-14", picked[0]["schedule"])

    def test_a_course_missing_from_the_live_answer_is_not_offered(self):
        picked = self.recommend({"2": ["20261215"]})
        self.assertEqual([row["course_id"] for row in picked], ["KMA-OFF-2"])

    def test_the_daily_answer_is_used_when_no_dates_are_passed(self):
        with patch("tap.account_insights.live_session_starts", return_value={"1": ["20261220"]}):
            self.assertEqual([row["next_start"] for row in self.recommend(None)], ["20261220"])


if __name__ == "__main__":
    unittest.main()
