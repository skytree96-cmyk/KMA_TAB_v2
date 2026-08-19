from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tap.dashboard import (
    build_kma_persistent_dashboard,
    build_persistent_dashboard,
    build_session_dashboard,
    completed_store_submission_factor_rows,
    completion_rate,
    fetch_store_snapshot,
    format_kma_organization_rows,
    load_dashboard_demo,
    normalize_target_means,
    validate_dashboard_demo,
)
from tap.data import questions_for_factors


ROOT = Path(__file__).resolve().parents[1]


def _stored_submission(
    participant_key: str,
    *,
    pre_complete: bool = True,
    post_complete: bool = False,
    updated_at: str = "2026-08-17T12:00:00+09:00",
) -> dict[str, object]:
    questions = questions_for_factors(["CORE-CO"])
    responses = {str(row["question_code"]): 3 for row in questions}
    return {
        "record_type": "submission",
        "project_id": "PROJECT-REAL-001",
        "participant_key": participant_key,
        "instrument": {
            "project_name": "실데이터 검증 교육",
            "assessment_version": "TAP-1.0",
            "target_level": "staff",
            "question_snapshot_hash": "hash-current",
            "question_snapshot_codes": [
                str(row["question_code"]) for row in questions
            ],
        },
        "phases": {
            "pre": {
                "responses": responses if pre_complete else {},
                "completed": pre_complete,
                "completed_at": "2026-08-01",
            },
            "post": {
                "responses": responses if post_complete else {},
                "completed": post_complete,
                "completed_at": "2026-08-17",
            },
        },
        "transition_responses": {},
        "updated_at": updated_at,
    }


class _FakeStore:
    def __init__(self, submissions: list[dict[str, object]]) -> None:
        self.submissions = submissions

    def list_projects(self) -> list[dict[str, object]]:
        return [
            {
                "project_id": "PROJECT-REAL-001",
                "project_name": "저장 프로젝트명",
            }
        ]

    def list_submissions(self, project_id: str | None = None) -> list[dict[str, object]]:
        if project_id is None:
            return list(self.submissions)
        return [row for row in self.submissions if row["project_id"] == project_id]


class DashboardTests(unittest.TestCase):
    def test_published_project_without_submissions_is_real_zero_state(self) -> None:
        projects = [
            {
                "record_type": "project",
                "project_id": "PROJECT-ZERO-001",
                "project_name": "제출 전 기획검증 프로젝트",
                "created_at": "2026-08-17T09:00:00+09:00",
                "updated_at": "2026-08-17T10:00:00+09:00",
            }
        ]

        dashboard = build_persistent_dashboard([], projects)
        kma_dashboard = build_kma_persistent_dashboard([], projects)

        self.assertTrue(dashboard["has_data"])
        self.assertTrue(dashboard["has_project"])
        self.assertFalse(dashboard["has_submissions"])
        self.assertEqual(1, len(dashboard["projects"]))
        self.assertEqual("제출 전 기획검증 프로젝트", dashboard["projects"][0]["name"])
        self.assertEqual("검사 대기", dashboard["projects"][0]["status"])
        self.assertEqual(0, dashboard["participant_count"])
        self.assertEqual(0, dashboard["pre_completed_count"])
        self.assertEqual(0, dashboard["post_completed_count"])
        self.assertEqual(0, dashboard["paired_count"])
        self.assertTrue(kma_dashboard["has_data"])
        self.assertFalse(kma_dashboard["has_submissions"])
        self.assertEqual("1개", kma_dashboard["metrics"][0]["value"])
        self.assertEqual("0명", kma_dashboard["metrics"][1]["value"])

    def test_kma_store_rows_are_current_snapshots_not_audit_events(self) -> None:
        dashboard = build_kma_persistent_dashboard(
            [_stored_submission("pk-snapshot", post_complete=True)]
        )
        rendered = str(dashboard)
        page_source = (ROOT / "pages" / "6_kma_dashboard.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("audit_events", dashboard)
        self.assertEqual("현재 완료 집계", dashboard["snapshot_rows"][0]["snapshot"])
        self.assertNotIn("권한 변경", rendered)
        self.assertNotIn("다운로드", rendered)
        self.assertNotIn("발행", rendered)
        self.assertIn('event_title = "최근 집계 갱신"', page_source)
        self.assertIn("감사 이벤트 이력이 아닙니다", page_source)
        self.assertIn('"최근 집계 갱신" if dashboard_source == "store"', page_source)

    def test_organization_report_uses_explicit_project_selection_before_csv(self) -> None:
        source = (ROOT / "pages" / "4_organization_report.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('"프로젝트 선택"', source)
        self.assertIn("실시 프로젝트에서 리포트 열기", source)
        self.assertIn('"CSV 파일로 직접 비교하기 · 보조 기능"', source)
        self.assertIn("CSV가 선택 프로젝트보다 우선합니다", source)
        self.assertIn("if uploaded is not None and use_uploaded:", source)
        self.assertIn('elif selected_project_key:', source)
        self.assertIn('stored_project.get("selected_factors")', source)

        audit_table = source.index('with st.expander("집계 검수표 보기"):')
        final_csv_tools = source.rfind("_render_csv_tools()")
        self.assertGreater(final_csv_tools, audit_table)
        self.assertTrue(
            source.rstrip().endswith("_render_csv_tools()"),
            "CSV 업로드는 프로젝트 리포트와 최종 검수표 뒤의 보조 영역이어야 합니다.",
        )

    def test_persistent_project_row_shows_reloadable_project_code(self) -> None:
        dashboard = build_persistent_dashboard(
            [_stored_submission("pk-code", post_complete=True)]
        )

        self.assertIn("코드 PROJECT-REAL-001", dashboard["projects"][0]["scope"])

    def test_fake_store_snapshot_and_persistent_counts(self) -> None:
        store = _FakeStore(
            [
                _stored_submission("pk-a", post_complete=True),
                _stored_submission("pk-b", post_complete=False),
                # Newest record wins for the same pseudonymous participant.
                _stored_submission(
                    "pk-b",
                    post_complete=True,
                    updated_at="2026-08-17T13:00:00+09:00",
                ),
            ]
        )
        snapshot = fetch_store_snapshot(store)
        dashboard = build_persistent_dashboard(
            snapshot["submissions"], snapshot["projects"]
        )

        self.assertTrue(dashboard["has_data"])
        self.assertEqual(1, len(dashboard["projects"]))
        self.assertEqual(2, dashboard["participant_count"])
        self.assertEqual(2, dashboard["pre_completed_count"])
        self.assertEqual(2, dashboard["post_completed_count"])
        self.assertEqual(2, dashboard["paired_count"])
        self.assertEqual("저장 프로젝트명", dashboard["projects"][0]["name"])

    def test_incomplete_store_submission_is_not_counted(self) -> None:
        dashboard = build_persistent_dashboard(
            [_stored_submission("pk-a", pre_complete=False, post_complete=False)]
        )

        self.assertFalse(dashboard["has_data"])
        self.assertEqual(0, dashboard["participant_count"])

    def test_completed_store_phase_requires_exact_instrument_response_keys(self) -> None:
        malformed = _stored_submission("pk-partial", post_complete=False)
        malformed["phases"]["pre"]["responses"].pop(
            next(iter(malformed["phases"]["pre"]["responses"]))
        )

        dashboard = build_persistent_dashboard([malformed])

        self.assertFalse(dashboard["has_data"])
        self.assertEqual(0, dashboard["pre_completed_count"])

    def test_kma_store_dashboard_never_displays_participant_keys(self) -> None:
        dashboard = build_kma_persistent_dashboard(
            [_stored_submission("secret-pseudonymous-key", post_complete=True)]
        )
        rendered = str(dashboard)

        self.assertTrue(dashboard["has_data"])
        self.assertNotIn("secret-pseudonymous-key", rendered)
        self.assertNotIn("participant_id", rendered)

    def test_kma_store_organization_columns_are_unique_and_project_scoped(self) -> None:
        dashboard = build_kma_persistent_dashboard(
            [_stored_submission("pk-table", post_complete=True)]
        )

        # Reproduce the previous persisted row shape: ``name`` and ``projects``
        # used to be renamed to the same display label before Arrow conversion.
        legacy_row = {**dashboard["organizations"][0], "projects": 1}
        rows = format_kma_organization_rows([legacy_row], persistent=True)

        self.assertEqual(1, len(rows))
        self.assertEqual(
            ["프로젝트", "검사 참여자", "사전·사후 모두 완료율(%)", "최근 집계 갱신"],
            list(rows[0]),
        )
        self.assertEqual(len(rows[0]), len(set(rows[0])))
        self.assertNotIn("projects", dashboard["organizations"][0])

    def test_kma_sample_organization_columns_remain_unique(self) -> None:
        rows = format_kma_organization_rows(
            load_dashboard_demo()["kma"]["organizations"], persistent=False
        )

        self.assertEqual(
            ["회원사", "프로젝트", "초대 인원", "완료율(%)", "최근 활동"],
            list(rows[0]),
        )
        self.assertEqual(len(rows[0]), len(set(rows[0])))

    def test_store_item_responses_convert_to_group_factor_rows(self) -> None:
        questions = questions_for_factors(["CORE-CO"])
        rows = completed_store_submission_factor_rows(
            [_stored_submission("pk-report", post_complete=True)],
            questions,
            project_id="PROJECT-REAL-001",
            question_snapshot_hash="hash-current",
        )

        self.assertEqual({"pre", "post"}, {row["session_type"] for row in rows})
        self.assertEqual({"pk-report"}, {row["participant_id"] for row in rows})
        self.assertEqual({"PROJECT-REAL-001"}, {row["project_id"] for row in rows})

    def test_normalize_target_means_excludes_invalid_persisted_values(self) -> None:
        warnings: list[str] = []

        normalized = normalize_target_means(
            {
                "VALID": "3.5",
                "TEXT": "not-a-number",
                "NAN": float("nan"),
                "INFINITE": float("inf"),
                "TOO-LOW": 0.9,
                "TOO-HIGH": 5.1,
                "": 3.0,
            },
            warnings=warnings,
        )

        self.assertEqual({"VALID": 3.5}, normalized)
        self.assertEqual(1, len(warnings))
        for code in ("TEXT", "NAN", "INFINITE", "TOO-LOW", "TOO-HIGH"):
            self.assertIn(code, warnings[0])

    def test_store_report_survives_invalid_persisted_target_mean(self) -> None:
        questions = questions_for_factors(["CORE-CO"])
        malformed = _stored_submission("pk-invalid-target", post_complete=True)
        malformed["instrument"]["target_means"] = {"CORE-CO": "oops"}
        warnings: list[str] = []

        rows = completed_store_submission_factor_rows(
            [malformed],
            questions,
            project_id="PROJECT-REAL-001",
            target_means={"CORE-CO": "also-invalid"},
            question_snapshot_hash="hash-current",
            warnings=warnings,
        )

        self.assertEqual({"pre", "post"}, {row["session_type"] for row in rows})
        self.assertEqual({"pk-invalid-target"}, {row["participant_id"] for row in rows})
        self.assertTrue(any("CORE-CO" in warning for warning in warnings))

    def test_store_report_excludes_mismatched_question_snapshot(self) -> None:
        questions = questions_for_factors(["CORE-CO"])
        wrong_codes = _stored_submission("pk-wrong-code", post_complete=True)
        wrong_codes["instrument"]["question_snapshot_codes"] = ["OTHER-01"]
        wrong_codes["phases"]["pre"]["responses"] = {"OTHER-01": 3}
        wrong_codes["phases"]["post"]["responses"] = {"OTHER-01": 3}
        wrong_hash = _stored_submission("pk-wrong-hash", post_complete=True)
        wrong_hash["instrument"]["question_snapshot_hash"] = "hash-other"
        warnings: list[str] = []

        rows = completed_store_submission_factor_rows(
            [wrong_codes, wrong_hash],
            questions,
            project_id="PROJECT-REAL-001",
            question_snapshot_hash="hash-current",
            warnings=warnings,
        )

        self.assertEqual([], rows)
        self.assertEqual(2, len(warnings))
        self.assertIn("문항 코드 구성", warnings[0])
        self.assertIn("스냅샷 버전", warnings[1])

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

    def test_manager_dashboard_renders_current_session_instead_of_company_mock(self) -> None:
        app = AppTest.from_file(
            str(ROOT / "pages" / "9_manager_dashboard.py"), default_timeout=20
        ).run()
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

    def test_manager_entrypoint_guards_local_modules_without_runtime_reload(self) -> None:
        source = (ROOT / "pages" / "9_manager_dashboard.py").read_text(
            encoding="utf-8"
        )
        symbol_import = source.index("from tap.dashboard import (")
        guard_call = source.index(
            'stop_on_stale(st, ("tap.dashboard", "tap.github_demo_store", "tap.ui"))'
        )

        self.assertLess(guard_call, symbol_import)
        self.assertNotIn("reload(", source)

    def test_root_entrypoint_renders_public_open_page_iframe(self) -> None:
        app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=20).run()

        self.assertFalse(app.exception)
        iframes = app.get("iframe")
        self.assertEqual(1, len(iframes))
        source = str(iframes[0].proto.srcdoc)
        self.assertIn("현업 행동의 변화", source)
        self.assertNotIn("DATA TRANSPARENCY", source)
        self.assertNotIn("현재 저장 방식", source)
        self.assertNotIn("짝지은", source)
        self.assertNotIn("소표본 보호", source)
        self.assertIn('/pre_assessment?tap_role=participant', source)
        self.assertIn('/project_setup?tap_role=company', source)
        self.assertIn('target="_top"', source)

    def test_public_deep_link_sets_the_destination_role(self) -> None:
        app = AppTest.from_file(
            str(ROOT / "pages" / "7_pre_assessment.py"), default_timeout=20
        )
        app.query_params["tap_role"] = "participant"
        app.run()

        self.assertFalse(app.exception)
        self.assertEqual("participant", app.session_state.active_role)
        self.assertTrue(
            any("참여자 교육평가 화면" in str(item.value) for item in app.markdown)
        )

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
