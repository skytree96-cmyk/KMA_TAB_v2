from __future__ import annotations

import unittest

from streamlit.testing.v1 import AppTest


APP = r"""
import streamlit as st
from unittest.mock import patch
from tap.account_admin_ui import _render_projects

projects = [
    {"id": "p1", "company_id": "co1", "company_name": "한국능률협회",
     "name": "Leadership Pilot", "config": {"course_name": "AI 리더십"}},
    {"id": "p2", "company_id": "co1", "company_name": "한국능률협회",
     "project_name": "협업 역량 강화", "config": {"course_name": "Data Literacy"}},
    {"id": "p3", "company_id": "co2", "company_name": "미래기업",
     "name": "디지털 전환", "config": {"course_name": "AI 활용"}},
]
class Store:
    def list_assignments(self, token, project_id):
        st.session_state["last_assignment_project"] = project_id
        return []

def report(store, token, project):
    st.write("REPORT: " + project["id"])

with patch("tap.account_reports.render_project_report", side_effect=report):
    _render_projects(Store(), "test-token", {"role": ROLE, "company_id": "co1"}, projects, [])
"""


class AccountProjectSearchTests(unittest.TestCase):
    def app(self, role="kma"):
        app = AppTest.from_string(APP.replace("ROLE", repr(role))).run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def search(self, app, query):
        app.text_input(key="account_admin_project_search").input(query).run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def reports(self, app):
        return [item.value for item in app.markdown if item.value.startswith("REPORT: ")]

    def test_search_matches_company_project_or_course_and_normalizes_query(self):
        app = self.app()
        self.assertIsNone(app.selectbox[0].value)
        self.assertEqual(self.reports(app), [])
        for query, labels in (
            ("능률", ["Leadership Pilot · 한국능률협회 · AI 리더십", "협업 역량 강화 · 한국능률협회 · Data Literacy"]),
            ("  LEADERSHIP  ", ["Leadership Pilot · 한국능률협회 · AI 리더십"]),
            ("역량", ["협업 역량 강화 · 한국능률협회 · Data Literacy"]),
            ("  data LITERACY ", ["협업 역량 강화 · 한국능률협회 · Data Literacy"]),
            ("ai", ["Leadership Pilot · 한국능률협회 · AI 리더십", "디지털 전환 · 미래기업 · AI 활용"]),
            ("   ", ["Leadership Pilot · 한국능률협회 · AI 리더십", "협업 역량 강화 · 한국능률협회 · Data Literacy", "디지털 전환 · 미래기업 · AI 활용"]),
        ):
            with self.subTest(query=query):
                self.search(app, query)
                self.assertEqual(app.selectbox[0].options, labels)
                self.assertIsNone(app.selectbox[0].value)
                self.assertIn(f"검색 결과 {len(labels)}개 · 전체 3개", [item.value for item in app.caption])
                self.assertEqual(self.reports(app), [])

    def test_filter_retains_selected_project_or_clears_it_without_automatic_replacement(self):
        app = self.app()
        app.selectbox[0].select("p1").run(timeout=30)
        self.assertEqual(self.reports(app), ["REPORT: p1"])
        self.search(app, "리더십")
        self.assertEqual(app.selectbox[0].value, "p1")
        self.assertEqual(self.reports(app), ["REPORT: p1"])
        self.search(app, "data")
        self.assertIsNone(app.selectbox[0].value)
        self.assertEqual(self.reports(app), [])
        app.selectbox[0].select("p2").run(timeout=30)
        self.assertEqual(self.reports(app), ["REPORT: p2"])
        self.search(app, "존재하지않는과정")
        self.assertEqual(len(app.selectbox), 0)
        self.assertIsNone(app.session_state["account_admin_project_select"])
        self.assertTrue(any("검색 결과가 없습니다." in item.value for item in app.info))
        self.assertIn("검색 결과 0개 · 전체 3개", [item.value for item in app.caption])
        self.assertEqual(self.reports(app), [])
        self.search(app, "")
        self.assertIsNone(app.selectbox[0].value)
        self.assertEqual(self.reports(app), [])

    def test_company_manager_search_never_exposes_another_company_project(self):
        app = self.app("company")
        self.assertEqual(len(app.selectbox[0].options), 2)
        self.search(app, "미래기업")
        self.assertEqual(len(app.selectbox), 0)
        self.assertIn("검색 결과 0개 · 전체 2개", [item.value for item in app.caption])
        self.assertEqual(self.reports(app), [])
        self.assertNotIn("last_assignment_project", app.session_state.filtered_state)
        self.search(app, "AI")
        self.assertEqual(app.selectbox[0].options, ["Leadership Pilot · 한국능률협회 · AI 리더십"])
        self.assertIsNone(app.selectbox[0].value)
        app.selectbox[0].select("p1").run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(self.reports(app), ["REPORT: p1"])
        self.assertEqual(app.session_state["last_assignment_project"], "p1")


if __name__ == "__main__":
    unittest.main()
