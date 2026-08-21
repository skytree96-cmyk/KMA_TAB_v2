from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import streamlit as st
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
from tap.github_demo_store import DemoStoreConfig
from tap.tenant import derive_company_identity, hash_company_access_code


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

    def test_kma_dashboard_lists_company_registry_and_reviews_pending_company(self) -> None:
        company_id = "org_" + "a" * 64
        management_code = "kma-review-code"
        config = DemoStoreConfig(
            enabled=True,
            owner="example",
            repo="tap-demo",
            token="github-test-token",
            salt="dashboard-company-list-salt",
            company_access_code=management_code,
        )
        stored_submission = _stored_submission("pk-company", post_complete=True)
        stored_submission["company_id"] = company_id
        store = MagicMock()
        store.status.return_value = {"read_enabled": True}
        store.list_companies.return_value = [
            {
                "company_id": company_id,
                "company_name": "승인 대기 테스트 기업",
                "company_identity_source": "business_registration",
                "approval_status": "pending",
                "requested_at": "2026-08-21T08:00:00+09:00",
            }
        ]
        store.list_projects.return_value = [
            {
                "record_type": "project",
                "company_id": company_id,
                "project_id": "PROJECT-REAL-001",
                "project_name": "승인 흐름 테스트",
                "updated_at": "2026-08-21T08:30:00+09:00",
            },
            {
                "record_type": "project",
                "project_id": "PROJECT-LEGACY-001",
                "project_name": "기업 범위 도입 전 프로젝트",
                "updated_at": "2026-08-01T08:30:00+09:00",
            },
        ]
        legacy_submission = _stored_submission("pk-legacy", post_complete=False)
        store.list_submissions.return_value = [stored_submission, legacy_submission]

        st.cache_data.clear()
        with (
            patch(
                "tap.github_demo_store.DemoStoreConfig.from_sources",
                return_value=config,
            ),
            patch("tap.github_demo_store.GitHubDemoStore", return_value=store),
        ):
            app = AppTest.from_file(
                str(ROOT / "pages" / "6_kma_dashboard.py"), default_timeout=30
            ).run()

            self.assertFalse(app.exception)
            company_frame = next(
                item.value
                for item in app.dataframe
                if "승인 상태" in item.value.columns
            )
            self.assertEqual("승인 대기 테스트 기업", company_frame.iloc[0]["회사명"])
            self.assertEqual("승인 대기", company_frame.iloc[0]["승인 상태"])
            self.assertEqual("1개 회사", company_frame.iloc[0]["관리자 범위"])
            self.assertEqual(1, company_frame.iloc[0]["프로젝트"])
            self.assertEqual(1, company_frame.iloc[0]["교육 전 완료"])
            self.assertEqual(1, company_frame.iloc[0]["교육 후 완료"])
            self.assertEqual("기존 미분류 데이터", company_frame.iloc[1]["회사명"])
            self.assertEqual("회사 연결 필요", company_frame.iloc[1]["승인 상태"])
            self.assertEqual("기업 정보 없음", company_frame.iloc[1]["관리자 범위"])
            self.assertEqual(1, company_frame.iloc[1]["프로젝트"])
            self.assertEqual(1, company_frame.iloc[1]["교육 전 완료"])
            self.assertEqual(0, company_frame.iloc[1]["교육 후 완료"])

            next(
                item
                for item in app.text_input
                if item.label == "KMA 승인관리 코드"
            ).set_value(management_code)
            next(item for item in app.button if item.label == "기업 승인").click()
            app.run()

        store.list_companies.assert_called()
        store.review_company_registration.assert_called_once_with(
            company_id,
            "approved",
            reviewer_note="",
        )

    def test_kma_company_registry_ui_does_not_request_or_display_raw_business_number(self) -> None:
        source = (ROOT / "pages" / "6_kma_dashboard.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('"companies": store.list_companies()', source)
        self.assertIn("review_company_registration(", source)
        self.assertIn("company_registration_code=management_code", source)
        self.assertIn("사업자등록번호 원문과 개인 관리자 정보는", source)
        self.assertNotIn('st.text_input("사업자등록번호"', source)
        self.assertLess(
            source.index("review_config.company_access_granted(management_code)"),
            source.index("review_store.review_company_registration("),
        )

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
        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        business_number = "101-81-12345"
        business_proof = "1018112345"
        config = DemoStoreConfig(
            enabled=True,
            owner="example",
            repo="tap-demo",
            salt="dashboard-tenant-salt",
        )
        identity = derive_company_identity(
            salt=config.salt,
            company_name="대시보드 테스트 기업",
            business_registration_number=business_number,
        )
        store = MagicMock()
        store.load_company.return_value = {
            "company_id": identity.company_id,
            "company_name": identity.company_name,
            "company_identity_source": identity.identity_source,
            "company_access_digest": hash_company_access_code(
                identity.company_id, business_proof, config.salt
            ),
            "approval_status": "approved",
        }
        # Keep this assertion focused on the documented browser-session fallback.
        # The company gate is still completed normally before any dashboard data
        # becomes visible.
        store.status.return_value = {"read_enabled": False}

        with (
            patch(
                "tap.github_demo_store.DemoStoreConfig.from_sources",
                return_value=config,
            ),
            patch("tap.github_demo_store.GitHubDemoStore", return_value=store),
            patch("tap.company_scope_ui.GitHubDemoStore", return_value=store),
        ):
            app = AppTest.from_file(
                str(ROOT / "pages" / "9_manager_dashboard.py"), default_timeout=20
            ).run()
            next(item for item in app.text_input if item.label == "회사명").set_value(
                identity.company_name
            )
            next(
                item for item in app.text_input if item.label == "사업자등록번호"
            ).set_value(business_number)
            next(
                item for item in app.button if item.label == "회사 확인·참여 요청"
            ).click()
            app.run()

            app.session_state["project_id"] = "TAP-REAL-001"
            app.session_state["project_name"] = "실제 세션 교육"
            app.session_state["selected_factors"] = ["CORE-CO"]
            app.session_state["participant_id"] = "EDU-P001"
            app.session_state["responses_by_phase"] = {
                "pre": {"CORE-CO-01": 4},
                "post": {},
            }
            app.session_state["assessment_completed_by_phase"] = {
                "pre": True,
                "post": False,
            }
            app.run()

        self.assertFalse(app.exception)
        rendered = "\n".join(str(item.value) for item in app.markdown)
        notices = "\n".join(str(item.value) for item in app.info)
        self.assertIn("실제 세션 교육", rendered)
        self.assertIn("현재 브라우저 세션", notices)
        self.assertNotIn("83.8%", rendered)
        self.assertNotIn("216명", rendered)

    def test_manager_entrypoint_guards_local_modules_without_runtime_reload(self) -> None:
        source = (ROOT / "pages" / "9_manager_dashboard.py").read_text(
            encoding="utf-8"
        )
        symbol_import = source.index("from tap.dashboard import (")
        guard_call = source.index("stop_on_stale(")

        self.assertLess(guard_call, symbol_import)
        for module_name in (
            "tap.company_scope_ui",
            "tap.dashboard",
            "tap.github_demo_store",
            "tap.tenant",
            "tap.ui",
        ):
            self.assertIn(f'"{module_name}"', source[guard_call:symbol_import])
        self.assertNotIn("reload(", source)

    def test_root_entrypoint_renders_public_open_page_html(self) -> None:
        app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=20).run()

        self.assertFalse(app.exception)
        html_nodes = app.get("html")
        self.assertEqual(1, len(html_nodes))
        self.assertEqual(0, len(app.get("iframe")))
        self.assertTrue(html_nodes[0].proto.unsafe_allow_javascript)
        source = str(html_nodes[0].proto.body)
        self.assertIn("현업 행동의 변화", source)
        self.assertNotIn("DATA TRANSPARENCY", source)
        self.assertNotIn("현재 저장 방식", source)
        self.assertNotIn("짝지은", source)
        self.assertNotIn("소표본 보호", source)
        self.assertIn('/pre_assessment?tap_role=participant', source)
        self.assertIn('/project_setup?tap_role=company', source)
        self.assertNotIn('target="_top"', source)
        self.assertEqual(
            3, source.count(' data-guide-download href="/tap-user-guide.pdf"')
        )
        self.assertEqual(3, source.count('href="/tap-user-guide.pdf"'))
        self.assertEqual(3, source.count('download="TAP_사용설명서_v3.pdf"'))
        self.assertIn("JVBERi0", source)
        self.assertNotIn("__TAP_GUIDE_PDF_BASE64__", source)
        self.assertIn("landingDocument.addEventListener('click'", source)
        self.assertIn("target.scrollIntoView", source)
        self.assertIn("streamlitMain.scrollBy", source)
        self.assertIn("scrollToSection", source)
        self.assertNotIn('href="#roles">검사 참여</a>', source)
        self.assertNotIn('href="#roles">프로젝트 코드로 검사 참여</a>', source)
        self.assertGreaterEqual(
            source.count(
                'data-app-link href="https://kmatap.streamlit.app/'
                'pre_assessment?tap_role=participant"'
            ),
            4,
        )
        for route in (
            "/organization_report?tap_role=company",
            "/project_setup?tap_role=company",
            "/pre_assessment?tap_role=participant",
            "/post_assessment?tap_role=participant",
            "/kma_dashboard?tap_role=kma",
        ):
            self.assertIn(f'href="https://kmatap.streamlit.app{route}"', source)
        self.assertNotIn(
            'organization_report?tap_role=company" target="_blank"', source
        )

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
