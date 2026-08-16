from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tap.dashboard import (
    build_session_dashboard,
    completion_rate,
    load_dashboard_demo,
    validate_dashboard_demo,
)


ROOT = Path(__file__).resolve().parents[1]


class DashboardTests(unittest.TestCase):
    def test_empty_session_does_not_show_mock_activity(self) -> None:
        dashboard = build_session_dashboard(
            {
                "project_id": "",
                "selected_factors": [],
                "participant_id": "",
                "responses_by_phase": {"pre": {}, "post": {}},
                "assessment_completed_by_phase": {"pre": False, "post": False},
            }
        )

        self.assertFalse(dashboard["has_project"])
        self.assertEqual(0, dashboard["participant_count"])
        self.assertEqual([], dashboard["projects"])
        self.assertEqual(
            ["0개", "0명", "대기", "대기"],
            [metric["value"] for metric in dashboard["metrics"]],
        )

    def test_session_dashboard_uses_actual_pre_post_state(self) -> None:
        dashboard = build_session_dashboard(
            {
                "project_id": "TAP-REAL-001",
                "project_name": "실제 리더십 교육",
                "selected_factors": ["CORE-CO", "CORE-PB"],
                "participant_id": "EDU-P001",
                "responses_by_phase": {
                    "pre": {"Q1": 3, "Q2": 4},
                    "post": {"Q1": 4},
                },
                "assessment_completed_by_phase": {"pre": True, "post": False},
            }
        )

        self.assertTrue(dashboard["has_project"])
        self.assertEqual(1, dashboard["participant_count"])
        self.assertEqual(0, dashboard["paired_count"])
        self.assertEqual(50, dashboard["phase_completion_pct"])
        self.assertEqual(2, dashboard["pre_response_count"])
        self.assertEqual(1, dashboard["post_response_count"])
        self.assertEqual("실제 리더십 교육", dashboard["projects"][0]["name"])
        self.assertEqual("진행 중", dashboard["projects"][0]["status"])
        self.assertEqual(0, dashboard["projects"][0]["completed"])
        self.assertEqual(1, dashboard["projects"][0]["invited"])
        self.assertEqual(0, dashboard["projects"][0]["completion_pct"])
        self.assertEqual(
            ["1개", "1명", "완료", "미완료"],
            [metric["value"] for metric in dashboard["metrics"]],
        )

    def test_session_dashboard_counts_complete_pair_only_after_both_phases(self) -> None:
        dashboard = build_session_dashboard(
            {
                "project_id": "TAP-REAL-001",
                "project_name": "실제 리더십 교육",
                "selected_factors": ["CORE-CO"],
                "participant_id": "EDU-P001",
                "responses_by_phase": {"pre": {"Q1": 3}, "post": {"Q1": 5}},
                "assessment_completed_by_phase": {"pre": True, "post": True},
            }
        )

        self.assertEqual(1, dashboard["paired_count"])
        self.assertEqual(100, dashboard["phase_completion_pct"])
        self.assertEqual(1, dashboard["projects"][0]["completed"])
        self.assertEqual(100, dashboard["projects"][0]["completion_pct"])
        self.assertEqual("완료", dashboard["projects"][0]["status"])

    def test_pre_only_row_is_zero_of_one_while_caption_progress_is_half(self) -> None:
        dashboard = build_session_dashboard(
            {
                "project_id": "TAP-REAL-001",
                "project_name": "실제 리더십 교육",
                "selected_factors": ["CORE-CO"],
                "participant_id": "EDU-P001",
                "responses_by_phase": {"pre": {"Q1": 3}, "post": {}},
                "assessment_completed_by_phase": {"pre": True, "post": False},
            }
        )

        self.assertEqual(50, dashboard["phase_completion_pct"])
        self.assertEqual(0, dashboard["projects"][0]["completion_pct"])
        self.assertEqual(0, dashboard["projects"][0]["completed"])
        self.assertEqual(1, dashboard["projects"][0]["invited"])

    def test_home_page_renders_current_session_instead_of_company_mock(self) -> None:
        app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=20).run()
        app.session_state["project_id"] = "TAP-REAL-001"
        app.session_state["project_name"] = "실제 세션 교육"
        app.session_state["selected_factors"] = ["CORE-CO"]
        app.session_state["participant_id"] = "EDU-P001"
        app.session_state["responses_by_phase"] = {
            "pre": {"CORE-CO-01": 4},
            "post": {},
        }
        app.session_state["assessment_completed_by_phase"] = {"pre": True, "post": False}
        app.run()

        self.assertFalse(app.exception)
        rendered = "\n".join(str(item.value) for item in app.markdown)
        notices = "\n".join(str(item.value) for item in app.info)
        self.assertIn("실제 세션 교육", rendered)
        self.assertIn("이 브라우저 세션", notices)
        self.assertNotIn("83.8%", rendered)
        self.assertNotIn("216명", rendered)

    def test_entrypoint_refreshes_local_modules_before_symbol_imports(self) -> None:
        source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        symbol_import = source.index("from tap.dashboard import build_session_dashboard")

        for module_name in (
            "_baseline_transfer_module",
            "_dashboard_module",
            "_ui_module",
        ):
            self.assertLess(source.index(f"reload({module_name})"), symbol_import)

    def test_demo_dashboard_contract(self) -> None:
        data = load_dashboard_demo()
        self.assertEqual(validate_dashboard_demo(data), [])

    def test_company_weighted_completion_rate(self) -> None:
        projects = load_dashboard_demo()["company"]["projects"]
        self.assertEqual(completion_rate(projects), 83.8)

    def test_kma_organization_rows_do_not_expose_scores(self) -> None:
        rows = load_dashboard_demo()["kma"]["organizations"]
        forbidden = {"score", "score_1_to_5", "gap", "individual_result", "responses"}
        for row in rows:
            self.assertTrue(forbidden.isdisjoint(row))


if __name__ == "__main__":
    unittest.main()
