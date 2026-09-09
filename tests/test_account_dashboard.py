from __future__ import annotations

import unittest
from datetime import date

from streamlit.testing.v1 import AppTest

from tap.account_dashboard import filter_projects, project_status, schedule_checks


PROJECT = {
    "id": "p1", "company_id": "co1", "company_name": "알파 교육", "name": "리더 성장",
    "assigned": 10, "pre_completed": 8, "post_completed": 3,
    "config": {"course_name": "AI Leadership", "selected_factors": [],
               "pre_start_date": "2026-10-01", "pre_end_date": "2026-10-07",
               "training_date": "2026-10-08", "post_start_date": "2026-12-03", "post_end_date": "2026-12-10"},
}


APP = '''
import streamlit as st
from tap.account_dashboard import render_dashboard
from tap.account_store import AuthenticationError, AuthorizationError
class Store:
    def dashboard_summary(self, token):
        st.session_state["reads"] = st.session_state.get("reads", []) + [("dashboard", token)]
        if st.session_state.get("denied"):
            raise AuthorizationError("internal cross-tenant detail")
        if st.session_state.get("expired"):
            raise AuthenticationError("internal expired token")
        role = st.session_state.get("role", "kma")
        projects = st.session_state["projects"]
        if role == "company" and not st.session_state.get("unscoped_fake"):
            projects = [row for row in projects if row["company_id"] == "co1"]
        return {"companies_count":2 if role == "kma" else 1,
                "company_users_count":2 if role == "kma" else 1,
                "participant_users_count":12 if role == "kma" else 10, "projects":projects,
                "participating_companies_count":2 if projects else 0,
                "participating_users_count":9 if role == "kma" and projects else (8 if projects else 0),
                "pre_completed_users_count":8 if projects else 0,"post_completed_users_count":3 if projects else 0,
                "company_participation":[], "completion_trend":[{"month":"2026-09","pre_completed":8,"post_completed":3}]}
    def project_results(self, token, project_id):
        st.session_state["reads"] = st.session_state.get("reads", []) + [("report", project_id)]
        return []
render_dashboard(Store(), "session-token", {"role":st.session_state.get("role", "kma"),
    "company_id":"co1", "company_name":"알파 교육"})
'''


class AccountDashboardTests(unittest.TestCase):
    def app(self, role="kma", **state):
        app = AppTest.from_string(APP)
        app.session_state["role"] = role
        app.session_state["projects"] = [PROJECT, {
            **PROJECT, "id": "p2", "company_id": "co2", "company_name": "Beta Academy", "name": "협업 강화",
            "assigned": 2, "pre_completed": 1, "post_completed": 0,
            "config": {**PROJECT["config"], "course_name": "Team Workshop"},
        }]
        for key, value in state.items():
            app.session_state[key] = value
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def test_kma_and_company_load_one_aggregate_and_render_scoped_counts(self):
        for role, expected in (("kma", ["2 개사", "9 명", "12 명", "2 개"]), ("company", ["8 명", "8 명", "3 명", "1 개"])):
            with self.subTest(role=role):
                app = self.app(role)
                self.assertEqual([metric.value for metric in app.metric], expected)
                self.assertEqual(app.session_state["reads"], [("dashboard", "session-token")])
                self.assertEqual([title.value for title in app.title], ["대시보드"])
                options = app.selectbox(key="account_dashboard_report").options
                self.assertEqual(len(options), 2 if role == "kma" else 1)
                self.assertEqual(len(app.tabs), 0)
                self.assertFalse(app.error)
                if role == "kma":
                    self.assertTrue(any("전체 등록 기업 2개사" in caption.value for caption in app.caption))
                else:
                    self.assertNotIn("Beta", str([frame.value for frame in app.dataframe]))
                    self.assertFalse(any(box.key == "account_dashboard_company" for box in app.selectbox))

    def test_participant_and_expired_or_denied_sessions_do_not_show_data(self):
        app = self.app("participant")
        self.assertTrue(app.error)
        self.assertNotIn("reads", app.session_state.filtered_state)
        for flag in ("denied", "expired"):
            with self.subTest(flag=flag):
                app = self.app(**{flag: True})
                self.assertTrue(app.error)
                self.assertEqual(len(app.metric), 0)
                self.assertEqual(len(app.dataframe), 0)
                self.assertNotIn("internal", app.error[0].value)

    def test_company_defensively_excludes_other_company_projects(self):
        app = self.app("company", unscoped_fake=True)
        self.assertEqual(app.metric[3].value, "1 개")
        self.assertEqual(len(app.selectbox(key="account_dashboard_report").options), 1)
        self.assertNotIn("Beta", str([frame.value for frame in app.dataframe]))

    def test_search_selects_a_real_report_and_clears_filtered_target(self):
        app = self.app()
        self.assertIsNone(app.selectbox(key="account_dashboard_report").value)
        app.text_input(key="account_dashboard_search").input("alpha").run()
        self.assertFalse(any(box.key == "account_dashboard_report" for box in app.selectbox))
        app.text_input(key="account_dashboard_search").input("lEaDeR").run()
        self.assertEqual(app.selectbox(key="account_dashboard_report").options, ["알파 교육 · 리더 성장 · AI Leadership"])
        app.selectbox(key="account_dashboard_report").set_value("p1").run()
        self.assertEqual(app.session_state["reads"][-1], ("report", "p1"))
        app.session_state["reads"] = []
        app.text_input(key="account_dashboard_search").input("beta").run()
        self.assertIsNone(app.selectbox(key="account_dashboard_report").value)
        self.assertEqual(app.session_state["reads"], [("dashboard", "session-token")])
        self.assertEqual(list(app.exception), [])

    def test_company_filter_and_pagination_limit_rendered_list(self):
        app = self.app()
        app.selectbox(key="account_dashboard_company").set_value("co2").run()
        self.assertEqual(app.selectbox(key="account_dashboard_report").options, ["Beta Academy · 협업 강화 · Team Workshop"])
        app = self.app(projects=[{**PROJECT, "id":f"p{i}", "name":f"교육 {i}"} for i in range(25)])
        self.assertEqual(len(app.selectbox(key="account_dashboard_report").options), 12)
        app.selectbox(key="account_dashboard_report").set_value("p0").run()
        app.session_state["reads"] = []
        app.number_input(key="account_dashboard_page").set_value(3).run()
        self.assertEqual(len(app.selectbox(key="account_dashboard_report").options), 1)
        self.assertIsNone(app.selectbox(key="account_dashboard_report").value)
        self.assertEqual(app.session_state["reads"], [("dashboard", "session-token")])
        self.assertEqual(list(app.exception), [])

    def test_empty_store_renders_zero_counts_without_demo_or_report(self):
        app = self.app(projects=[])
        self.assertEqual([metric.value for metric in app.metric], ["0 개사", "0 명", "12 명", "0 개"])
        self.assertTrue(any("등록된 프로젝트가 없습니다" in item.value for item in app.info))
        self.assertEqual(len(app.dataframe), 0)
        self.assertEqual(app.session_state["reads"], [("dashboard", "session-token")])

    def test_rates_handle_no_population_and_explain_denominator(self):
        from tap.account_dashboard import _rate
        self.assertEqual(_rate(0, 0), "—")
        self.assertEqual(_rate(1, 4), "25%")
        app = self.app()
        self.assertTrue(any("전체 등록 참여자" in item.value for item in app.caption))
        self.assertTrue(any("미배정·사용 중지 포함" in item.value for item in app.caption))
        self.assertTrue(any("전체 검사 완료 추세" in item.value for item in app.subheader))

    def test_phase_status_and_schedule_checks_use_inclusive_dates(self):
        expected = {
            "2026-09-30":"사전검사 예정", "2026-10-01":"사전검사 진행", "2026-10-07":"사전검사 진행",
            "2026-10-08":"사후검사 대기", "2026-12-02":"사후검사 대기", "2026-12-03":"사후검사 진행",
            "2026-12-10":"사후검사 진행", "2026-12-11":"사후검사 종료",
        }
        for day, status in expected.items():
            with self.subTest(day=day):
                self.assertEqual(project_status(PROJECT, date.fromisoformat(day)), status)
        checks = schedule_checks([PROJECT], date(2026, 12, 10))
        self.assertEqual([row["확인할 내용"] for row in checks], ["사전검사 마감 · 미완료 2명", "사후검사 진행 · 미완료 7명"])
        self.assertEqual(schedule_checks([{**PROJECT, "pre_completed":10, "post_completed":10}], date(2026, 12, 11)), [])
        self.assertEqual(project_status({**PROJECT, "post_completed":10}, date(2026, 12, 11)), "검사 완료")
        self.assertEqual(project_status({**PROJECT, "assigned":0}, date(2026, 12, 11)), "참여자 배정 필요")
        self.assertEqual(schedule_checks([{**PROJECT, "assigned":0}], date(2026, 12, 11))[0]["확인할 내용"], "참여자 배정 필요")
        self.assertEqual(project_status({**PROJECT, "config":{}}, date(2026, 12, 11)), "일정 확인 필요")
        same_day = {**PROJECT, "config": {key:"2026-10-08" for key in (
            "pre_start_date", "pre_end_date", "training_date", "post_start_date", "post_end_date")}}
        self.assertEqual(project_status(same_day, date(2026, 10, 8)), "사전·사후검사 진행")

    def test_search_matches_company_project_course_and_all_words(self):
        for query in ("알파", "성장", "lEaDeR", "알파 Leadership"):
            self.assertEqual(filter_projects([PROJECT], query), [PROJECT])
        self.assertEqual(filter_projects([PROJECT], "알파 unknown"), [])
        self.assertEqual(filter_projects([PROJECT], "", "co2"), [])


if __name__ == "__main__":
    unittest.main()
