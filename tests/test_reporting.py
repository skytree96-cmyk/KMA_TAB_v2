from __future__ import annotations

import re
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from tap.data import load_competencies, questions_for_factors
from tap.github_demo_store import DemoStoreConfig
from tap.reporting import (
    build_organization_report_model,
    build_pre_post_group_summary,
    completed_session_factor_rows,
    organization_report_fragment,
    prepare_group_results,
    printable_organization_report_html,
    read_group_results_csv,
)


COMPETENCIES = [
    {
        "factor_code": "F1",
        "factor_name_ko": "공식 한글명",
        "active_for_scoring": True,
    }
]
ROOT = Path(__file__).resolve().parents[1]


def _small_n_store_snapshot() -> tuple[dict[str, object], dict[str, object]]:
    project_id = "TAP-SMALL-N-PREVIEW"
    selected_factors = ["CORE-CO", "CORE-CL", "CORE-GM"]
    questions = questions_for_factors(selected_factors)
    question_codes = [str(row["question_code"]) for row in questions]
    pre_responses = {code: 2 for code in question_codes}
    post_responses = {code: 4 for code in question_codes}
    project: dict[str, object] = {
        "schema_version": 1,
        "demo_only": True,
        "record_type": "project",
        "project_id": project_id,
        "project_name": "소표본 화면 검증",
        "selected_factors": selected_factors,
        "question_snapshot_codes": question_codes,
        "question_snapshot_hash": "",
        "assessment_version": "TAP-1.0",
        "target_level": "staff",
        "target_means": {},
        "organization_priorities": [],
        "allow_schedule_override": True,
        "pre_start_date": "2026-08-01",
        "post_end_date": "2026-10-01",
        "updated_at": "2026-10-01T12:00:00Z",
    }
    submission: dict[str, object] = {
        "schema_version": 1,
        "demo_only": True,
        "record_type": "submission",
        "project_id": project_id,
        "participant_key": "p_" + "a" * 64,
        "instrument": {
            "assessment_version": "TAP-1.0",
            "target_level": "staff",
            "question_snapshot_hash": "",
            "question_snapshot_codes": question_codes,
            "selected_factors": selected_factors,
        },
        "phases": {
            "pre": {
                "responses": pre_responses,
                "completed": True,
                "completed_at": "2026-08-01",
            },
            "post": {
                "responses": post_responses,
                "completed": True,
                "completed_at": "2026-10-01",
            },
        },
        "transition_responses": {},
        "updated_at": "2026-10-01T12:00:00Z",
    }
    return project, submission


class ReportingTests(unittest.TestCase):
    def test_organization_report_uses_cloud_safe_svg_iframe(self) -> None:
        source = (ROOT / "pages" / "4_organization_report.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("st.iframe(", source)
        self.assertIn('height="content"', source)
        self.assertNotIn("streamlit.components.v1", source)
        self.assertNotIn("components.html(", source)
        self.assertNotIn('st.html(preview_radar["html"])', source)
        self.assertNotIn('st.html(radar["html"])', source)

    def test_group_csv_rejects_duplicate_headers_before_pandas_mangles_them(self) -> None:
        raw = (
            "participant_id,participant_id,factor_code,score_1_to_5\n"
            "P1,P2,CORE-CO,3.5\n"
        ).encode("utf-8")

        with self.assertRaisesRegex(ValueError, "CSV 열 이름이 중복.*participant_id"):
            read_group_results_csv(raw)

    def test_group_csv_preserves_leading_zero_participant_ids(self) -> None:
        frame = read_group_results_csv(
            (
                "participant_id,factor_code,score_1_to_5,session_type\n"
                "001,F1,2.0,pre\n"
                "1,F1,4.0,post\n"
            ).encode("utf-8")
        )

        self.assertEqual(["001", "1"], frame["participant_id"].tolist())
        clean, errors, _ = prepare_group_results(frame, COMPETENCIES)
        self.assertEqual([], errors)
        summary = build_pre_post_group_summary(clean, min_group_n=1)
        self.assertEqual(0, summary["paired_participant_count"])

    def test_individual_report_uses_canonical_common_item_export_and_direction(self) -> None:
        source = (ROOT / "pages" / "3_individual_report.py").read_text(encoding="utf-8")
        self.assertIn("csv_rows = completed_session_factor_rows(", source)
        self.assertIn('key=lambda row: abs(float(row["change"]))', source)
        self.assertIn('("time_process_support", "시간·프로세스 지원")', source)

    def test_completed_session_rows_are_real_canonical_pre_post_export(self) -> None:
        questions = questions_for_factors(["CORE-CO"])
        pre = {str(row["question_code"]): 2 for row in questions}
        post = {str(row["question_code"]): 4 for row in questions}
        rows = completed_session_factor_rows(
            questions,
            {"pre": pre, "post": post},
            {"pre": True, "post": True},
            participant_id=" REAL-P001 ",
            project_id="실제 교육",
            assessment_version="TAP-1.0",
            target_level="manager",
            assessment_dates={"pre": "2026-08-01", "post": "2026-10-01"},
            post_transfer_responses={
                "application_opportunity": 4,
                "supervisor_support": 3,
                "resources_authority": 5,
            },
        )

        self.assertEqual(["pre", "post"], [row["session_type"] for row in rows])
        self.assertEqual([2, 4], [row["score_1_to_5"] for row in rows])
        self.assertTrue(all(row["participant_id"] == "REAL-P001" for row in rows))
        self.assertIsNone(rows[0]["opportunity_1_to_5"])
        self.assertEqual(4, rows[1]["opportunity_1_to_5"])

        incomplete = completed_session_factor_rows(
            questions,
            {"pre": pre, "post": post},
            {"pre": True, "post": False},
            participant_id="REAL-P001",
            project_id="실제 교육",
            assessment_version="TAP-1.0",
            target_level="manager",
            assessment_dates={"pre": "2026-08-01", "post": "2026-10-01"},
        )
        self.assertEqual(["pre"], [row["session_type"] for row in incomplete])

    def test_upload_validation_applies_canonical_name(self) -> None:
        frame = pd.DataFrame(
            [{"participant_id": "P1", "factor_code": "F1", "factor_name_ko": "임의명", "score_1_to_5": 3.5}]
        )
        clean, errors, warnings = prepare_group_results(frame, COMPETENCIES)
        self.assertEqual(errors, [])
        self.assertEqual(clean.loc[0, "factor_name_ko"], "공식 한글명")
        self.assertTrue(any("공식 한글명" in warning for warning in warnings))

    def test_upload_validation_rejects_bad_score_and_unknown_factor(self) -> None:
        frame = pd.DataFrame(
            [{"participant_id": "P1", "factor_code": "UNKNOWN", "score_1_to_5": 6}]
        )
        _, errors, _ = prepare_group_results(frame, COMPETENCIES)
        self.assertTrue(any("1~5" in error for error in errors))
        self.assertTrue(any("등록되지 않은" in error for error in errors))

    def test_mixed_versions_are_rejected(self) -> None:
        frame = pd.DataFrame(
            [
                {"participant_id": "P1", "factor_code": "F1", "score_1_to_5": 3, "project_id": "P", "assessment_version": "A", "target_level": "staff", "assessment_date": "2026-08-01"},
                {"participant_id": "P2", "factor_code": "F1", "score_1_to_5": 4, "project_id": "P", "assessment_version": "B", "target_level": "staff", "assessment_date": "2026-08-02"},
            ]
        )
        _, errors, _ = prepare_group_results(frame, COMPETENCIES, require_metadata=True)
        self.assertTrue(any("assessment_version" in error for error in errors))

    def test_operational_upload_requires_complete_metadata(self) -> None:
        frame = pd.DataFrame(
            [{"participant_id": "P1", "factor_code": "F1", "score_1_to_5": 3}]
        )
        _, errors, _ = prepare_group_results(frame, COMPETENCIES, require_metadata=True)
        self.assertTrue(any("메타데이터" in error for error in errors))

        frame_with_blank = pd.DataFrame(
            [{"participant_id": "P1", "factor_code": "F1", "score_1_to_5": 3, "project_id": "", "assessment_version": "A", "target_level": "staff", "assessment_date": "2026-08-01"}]
        )
        _, blank_errors, _ = prepare_group_results(frame_with_blank, COMPETENCIES, require_metadata=True)
        self.assertTrue(any("project_id" in error and "빈 행" in error for error in blank_errors))

    def test_pre_post_upload_keeps_session_and_rejects_invalid_type(self) -> None:
        frame = pd.DataFrame(
            [
                {"participant_id": "P1", "factor_code": "F1", "score_1_to_5": 3, "session_type": "PRE"},
                {"participant_id": "P1", "factor_code": "F1", "score_1_to_5": 4, "session_type": "post"},
            ]
        )
        clean, errors, _ = prepare_group_results(frame, COMPETENCIES)
        self.assertEqual(errors, [])
        self.assertEqual(clean["session_type"].tolist(), ["pre", "post"])

        invalid = frame.copy()
        invalid.loc[1, "session_type"] = "after"
        _, invalid_errors, _ = prepare_group_results(invalid, COMPETENCIES)
        self.assertTrue(any("pre 또는 post" in error for error in invalid_errors))

        followup = frame.copy()
        followup.loc[1, "session_type"] = "followup"
        _, followup_errors, _ = prepare_group_results(followup, COMPETENCIES)
        self.assertTrue(any("추적검사" in error for error in followup_errors))

    def test_demo_schedule_override_downgrades_same_day_pair_to_warning(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "participant_id": "P1",
                    "factor_code": "F1",
                    "score_1_to_5": 3.0,
                    "project_id": "P-DEMO",
                    "assessment_version": "TAP-1.0",
                    "target_level": "staff",
                    "assessment_date": "2026-08-17",
                    "session_type": "pre",
                    "valid_items": 4,
                    "na_items": 0,
                    "missing_items": 0,
                },
                {
                    "participant_id": "P1",
                    "factor_code": "F1",
                    "score_1_to_5": 4.0,
                    "project_id": "P-DEMO",
                    "assessment_version": "TAP-1.0",
                    "target_level": "staff",
                    "assessment_date": "2026-08-17",
                    "session_type": "post",
                    "valid_items": 4,
                    "na_items": 0,
                    "missing_items": 0,
                },
            ]
        )

        _, strict_errors, _ = prepare_group_results(
            frame, COMPETENCIES, require_metadata=True
        )
        _, demo_errors, demo_warnings = prepare_group_results(
            frame,
            COMPETENCIES,
            require_metadata=True,
            allow_schedule_override=True,
        )

        self.assertTrue(any("사전검사일" in error for error in strict_errors))
        self.assertEqual([], demo_errors)
        self.assertTrue(any("날짜 경고" in warning for warning in demo_warnings))

    def test_group_pre_post_is_paired_and_reports_attrition(self) -> None:
        frame = pd.DataFrame(
            [
                {"participant_id": "P1", "factor_code": "F1", "factor_name_ko": "업무 소통", "score_1_to_5": 2.0, "session_type": "pre", "na_items": 1},
                {"participant_id": "P1", "factor_code": "F1", "factor_name_ko": "업무 소통", "score_1_to_5": 4.0, "session_type": "post", "na_items": 0},
                {"participant_id": "P2", "factor_code": "F1", "factor_name_ko": "업무 소통", "score_1_to_5": 3.0, "session_type": "pre", "na_items": 0},
                {"participant_id": "P2", "factor_code": "F1", "factor_name_ko": "업무 소통", "score_1_to_5": 4.0, "session_type": "post", "na_items": 0},
                {"participant_id": "P3", "factor_code": "F1", "factor_name_ko": "업무 소통", "score_1_to_5": 5.0, "session_type": "pre", "na_items": 0},
            ]
        )
        summary = build_pre_post_group_summary(frame, min_group_n=2)
        row = summary["comparison_rows"][0]
        self.assertEqual(row["paired_n"], 2)
        self.assertEqual(row["pre_mean"], 2.5)
        self.assertEqual(row["post_mean"], 4.0)
        self.assertEqual(row["change"], 1.5)
        self.assertEqual(summary["attrition_count"], 1)
        self.assertEqual(summary["pre_na_items"], 1)

    def test_printable_report_is_korean_paper_document(self) -> None:
        model = build_organization_report_model(
            [
                {
                    "factor_code": "F1",
                    "factor_name_ko": "업무 소통",
                    "n": 8,
                    "group_mean": 3.2,
                    "status": "공개",
                }
            ],
            participant_count=8,
            project_name="검증 프로젝트",
            report_period="2026-08-01 ~ 2026-08-12",
            is_sample=True,
            demo_target=3.5,
        )
        html = printable_organization_report_html(model)
        self.assertIn("조직 교육수요 리포트", html)
        self.assertIn("예시 데이터", html)
        self.assertIn("@page", html)
        self.assertIn("업무 소통", html)
        fragment = organization_report_fragment(model)
        self.assertEqual(fragment.count('<section class="tap-report-sheet'), 4)
        self.assertNotIn("\n", fragment)

    def test_printable_pre_post_report_has_paired_change_and_limits(self) -> None:
        summary = {
            "comparison_rows": [
                {
                    "factor_code": "F1",
                    "factor_name_ko": "업무 소통",
                    "pre_n": 8,
                    "post_n": 7,
                    "paired_n": 7,
                    "pre_mean": 3.0,
                    "post_mean": 3.6,
                    "change": 0.6,
                    "status": "공개",
                }
            ],
            "pre_participant_count": 8,
            "post_participant_count": 7,
            "paired_participant_count": 7,
            "attrition_count": 1,
            "attrition_rate": 12.5,
            "pre_na_items": 3,
            "post_na_items": 1,
            "transfer_factors": {"업무 적용기회": 3.8},
        }
        model = build_organization_report_model(
            [{"factor_code": "F1", "factor_name_ko": "업무 소통", "n": 7, "group_mean": 3.6}],
            participant_count=7,
            project_name="교육 전후 검증",
            report_period="2026-08-01 ~ 2026-09-15",
            pre_post_summary=summary,
        )
        html = printable_organization_report_html(model)
        self.assertIn("조직 교육 전·후 변화 리포트", html)
        self.assertIn("전·후 유효응답 N=7", html)
        self.assertIn("인과효과로 확정", html)
        self.assertIn("사후 이탈률", html)
        fragment = organization_report_fragment(model)
        self.assertEqual(fragment.count('<section class="tap-report-sheet'), 4)
        self.assertNotIn("\n", fragment)

    def test_printable_pre_post_report_paginates_31_factors(self) -> None:
        comparison_rows = [
            {
                "factor_code": f"F{index:02d}",
                "factor_name_ko": f"역량 {index:02d}",
                "pre_n": 8,
                "post_n": 8,
                "paired_n": 8,
                "pre_mean": 3.0,
                "post_mean": 3.5,
                "change": 0.5,
                "status": "공개",
            }
            for index in range(1, 32)
        ]
        summary = {
            "comparison_rows": comparison_rows,
            "pre_participant_count": 8,
            "post_participant_count": 8,
            "paired_participant_count": 8,
            "attrition_count": 0,
            "attrition_rate": 0.0,
            "pre_na_items": 0,
            "post_na_items": 0,
            "transfer_factors": {},
        }
        model = build_organization_report_model(
            [
                {
                    "factor_code": row["factor_code"],
                    "factor_name_ko": row["factor_name_ko"],
                    "n": 8,
                    "group_mean": row["post_mean"],
                }
                for row in comparison_rows
            ],
            participant_count=8,
            project_name="31역량 인쇄 검증",
            report_period="2026-08-01 ~ 2026-09-15",
            pre_post_summary=summary,
        )
        html = printable_organization_report_html(model)
        change_pages = re.findall(
            r'<section class="tap-report-sheet tap-report-change-page">.*?</section>',
            html,
            flags=re.DOTALL,
        )
        detail_pages = re.findall(
            r'<section class="tap-report-sheet tap-report-detail-page">.*?</section>',
            html,
            flags=re.DOTALL,
        )

        self.assertEqual(len(change_pages), 4)
        self.assertEqual(len(detail_pages), 3)
        self.assertEqual(html.count('<section class="tap-report-sheet'), 9)
        self.assertTrue(all(page.count('class="tap-change-row"') <= 10 for page in change_pages))
        self.assertTrue(all(page.count("<tbody>") == 1 for page in detail_pages))
        self.assertTrue(
            all(page.split("<tbody>", 1)[1].split("</tbody>", 1)[0].count("<tr>") <= 12 for page in detail_pages)
        )
        for index in range(1, 32):
            self.assertIn(f"역량 {index:02d}", html)

    def test_individual_report_renders_phase_store_comparison(self) -> None:
        questions = questions_for_factors(["CORE-CO"])
        pre = {str(row["question_code"]): 2 for row in questions}
        post = {str(row["question_code"]): 4 for row in questions}
        app = AppTest.from_file(str(ROOT / "pages" / "3_individual_report.py"), default_timeout=30).run()
        app.session_state["selected_factors"] = ["CORE-CO"]
        app.session_state["target_means"] = {"CORE-CO": 3.5}
        app.session_state["responses_by_phase"] = {"pre": pre, "post": post}
        app.session_state["assessment_completed_by_phase"] = {"pre": True, "post": True}
        app.session_state["duration_seconds_by_phase"] = {"pre": 60, "post": 60}
        app.session_state["post_transfer_responses"] = {
            "application_opportunity": 4,
            "supervisor_support": 3,
            "resources_authority": 4,
        }
        app.run()
        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertTrue(
            any("교육 전·후 비교" in str(item.value) for item in app.markdown)
        )
        self.assertTrue(any(item.label == "관찰 변화 평균" for item in app.metric))
        self.assertTrue(any("실제 교육 전·후 완료 응답" in str(item.value) for item in app.success))

    def test_completed_pre_report_offers_private_baseline_download(self) -> None:
        questions = questions_for_factors(["CORE-CO"])
        pre = {str(row["question_code"]): 3 for row in questions}
        app = AppTest.from_file(str(ROOT / "pages" / "3_individual_report.py"), default_timeout=30).run()
        app.session_state["selected_factors"] = ["CORE-CO"]
        app.session_state["participant_id"] = "EDU-P001"
        app.session_state["responses_by_phase"] = {"pre": pre, "post": {}}
        app.session_state["assessment_completed_by_phase"] = {"pre": True, "post": False}
        app.session_state["question_snapshot_codes"] = [
            str(row["question_code"]) for row in questions
        ]
        app.session_state["question_snapshot_hash"] = "a" * 64
        app.session_state["assessment_version"] = "TAP-1.0+aaaaaaaaaaaa"
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        button = next(
            item for item in app.get("download_button")
            if item.label == "1. 교육 전 검사 기준파일 저장"
        )
        self.assertEqual("1. 교육 전 검사 기준파일 저장", button.label)
        source = (ROOT / "pages" / "3_individual_report.py").read_text(encoding="utf-8")
        self.assertIn('f"tap_pre_baseline_{project_token}_{completed_at}.json"', source)
        self.assertTrue(any("일반 결과 JSON과 다른" in str(item.value) for item in app.caption))
        self.assertTrue(any("본인만 안전하게 보관" in str(item.value) for item in app.caption))
        self.assertTrue(
            any("교육 전 완료 결과" in str(item.value) for item in app.markdown)
        )
        self.assertTrue(any(item.label == "교육 후 검사 시작" for item in app.button))
        self.assertIn('"post": "pages/8_post_assessment.py"', source)

    def test_incomplete_single_phase_hides_provisional_results_and_exports(self) -> None:
        questions = questions_for_factors(["CORE-CO"])
        first_code = str(questions[0]["question_code"])

        for responses in ({}, {first_code: 3}):
            with self.subTest(answered=len(responses)):
                app = AppTest.from_file(
                    str(ROOT / "pages" / "3_individual_report.py"), default_timeout=30
                ).run()
                app.session_state["selected_factors"] = ["CORE-CO"]
                app.session_state["assessment_phase"] = "pre"
                app.session_state["responses_by_phase"] = {"pre": responses, "post": {}}
                app.session_state["assessment_completed_by_phase"] = {
                    "pre": False,
                    "post": False,
                }
                app.run()

                self.assertEqual([], [str(item.value) for item in app.exception])
                self.assertTrue(
                    any("교육 전 검사 진행 중" in str(item.value) for item in app.markdown)
                )
                saved = next(item for item in app.metric if item.label == "저장된 응답")
                self.assertEqual(f"{len(responses)}/{len(questions)}문항", saved.value)
                self.assertTrue(
                    any("임시 점수·교육 추천·결과 파일" in str(item.value) for item in app.warning)
                )
                self.assertTrue(
                    any(item.label == "교육 전 검사로 돌아가기" for item in app.button)
                )
                self.assertFalse(app.dataframe)
                download_labels = {item.label for item in app.get("download_button")}
                self.assertNotIn("결과 JSON", download_labels)
                self.assertNotIn("결과 CSV", download_labels)
                self.assertNotIn("1. 교육 전 검사 기준파일 저장", download_labels)
                self.assertFalse(app.checkbox)

    def test_organization_report_uses_completed_session_before_sample(self) -> None:
        questions = questions_for_factors(["CORE-CO"])
        pre = {str(row["question_code"]): 2 for row in questions}
        post = {str(row["question_code"]): 4 for row in questions}
        app = AppTest.from_file(str(ROOT / "pages" / "4_organization_report.py"), default_timeout=30).run()
        app.session_state["selected_factors"] = ["CORE-CO"]
        app.session_state["participant_id"] = "REAL-P001"
        app.session_state["responses_by_phase"] = {"pre": pre, "post": post}
        app.session_state["assessment_completed_by_phase"] = {"pre": True, "post": True}
        app.session_state["pre_end_date"] = "2026-08-01"
        app.session_state["post_end_date"] = "2026-10-01"
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertTrue(any(item.label == "프로젝트 선택" for item in app.selectbox))
        self.assertTrue(
            any(
                item.label == "CSV 파일로 직접 비교하기 · 보조 기능"
                for item in app.expander
            )
        )
        self.assertTrue(any("실제 교육 전·후 결과" in str(item.value) for item in app.success))
        self.assertTrue(any("실제 완료 결과 1명" in str(item.value) for item in app.warning))
        self.assertTrue(any(item.label == "내 실제 교육 전·후 비교 보기" for item in app.button))
        self.assertFalse(any("합성 예시" in str(item.value) for item in app.warning))
        self.assertFalse(
            any(item.label == "리포트 미리보기 코드" for item in app.text_input),
            "현재 브라우저 결과에는 관리자용 소표본 미리보기를 열어서는 안 됩니다.",
        )
        self.assertEqual(
            {"교육 전 완료", "교육 후 완료", "전·후 모두 완료"},
            {item.label for item in app.metric},
            "N<5에서는 완료 건수만 보여주고 평균·변화량 조직 지표는 숨겨야 합니다.",
        )

    def test_small_n_store_preview_requires_code_and_explicit_opt_in(self) -> None:
        preview_code = "report-preview-secret"
        config = DemoStoreConfig(
            enabled=True,
            owner="example",
            repo="tap-demo",
            report_preview_code=preview_code,
        )
        project, submission = _small_n_store_snapshot()
        store = MagicMock()
        store.status.return_value = {"read_enabled": True}
        store.list_projects.return_value = [project]
        store.list_submissions.return_value = [submission]

        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        with (
            patch(
                "tap.github_demo_store.DemoStoreConfig.from_sources",
                return_value=config,
            ),
            patch("tap.github_demo_store.GitHubDemoStore", return_value=store),
        ):
            app = AppTest.from_file(
                str(ROOT / "pages" / "4_organization_report.py"),
                default_timeout=30,
            ).run()

            self.assertEqual([], [str(item.value) for item in app.exception])
            code_input = next(
                item for item in app.text_input if item.label == "리포트 미리보기 코드"
            )
            preview_toggle = next(
                item
                for item in app.toggle
                if item.label == "소표본 실제값을 화면에서만 미리보기"
            )
            self.assertTrue(preview_toggle.disabled)
            self.assertFalse(any(item.label == "교육 전 참여" for item in app.metric))
            self.assertFalse(any("외부 공유·캡처" in str(item.value) for item in app.warning))

            code_input.set_value("wrong-code")
            app.run()
            preview_toggle = next(
                item
                for item in app.toggle
                if item.label == "소표본 실제값을 화면에서만 미리보기"
            )
            self.assertTrue(preview_toggle.disabled)
            self.assertFalse(any(item.label == "교육 전 참여" for item in app.metric))

            next(
                item for item in app.text_input if item.label == "리포트 미리보기 코드"
            ).set_value(preview_code)
            app.run()
            preview_toggle = next(
                item
                for item in app.toggle
                if item.label == "소표본 실제값을 화면에서만 미리보기"
            )
            self.assertFalse(preview_toggle.disabled)
            preview_toggle.set_value(True)
            app.run()

            self.assertEqual([], [str(item.value) for item in app.exception])
            self.assertTrue(any(item.label == "교육 전 참여" for item in app.metric))
            self.assertTrue(any(item.label == "전·후 비교 참여자" for item in app.metric))
            self.assertTrue(
                any("외부 공유·캡처·인쇄 금지" in str(item.value) for item in app.warning)
            )
            self.assertFalse(
                any(item.label == "소표본 역량별 값 보기" for item in app.expander)
            )
            self.assertEqual(0, len(app.dataframe))
            preview_downloads = {item.label for item in app.get("download_button")}
            self.assertNotIn("인쇄용 리포트 HTML", preview_downloads)
            self.assertNotIn("상세 결과 CSV", preview_downloads)
            self.assertNotIn("사전·사후 CSV 양식", preview_downloads)
            self.assertFalse(
                any(
                    item.label == "CSV 파일로 직접 비교하기 · 보조 기능"
                    for item in app.expander
                )
            )
            lock_button = next(
                item for item in app.button if item.label == "미리보기 잠금"
            )
            lock_button.click()
            app.run()
            self.assertEqual("", next(
                item for item in app.text_input if item.label == "리포트 미리보기 코드"
            ).value)
            self.assertFalse(any(item.label == "교육 전 참여" for item in app.metric))

    def test_small_n_preview_reuses_legacy_access_code_in_same_session(self) -> None:
        legacy_code = "legacy-planning-code"
        config = DemoStoreConfig(
            enabled=True,
            owner="example",
            repo="tap-demo",
            access_code=legacy_code,
        )
        project, submission = _small_n_store_snapshot()
        store = MagicMock()
        store.status.return_value = {"read_enabled": True}
        store.list_projects.return_value = [project]
        store.list_submissions.return_value = [submission]

        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        with (
            patch(
                "tap.github_demo_store.DemoStoreConfig.from_sources",
                return_value=config,
            ),
            patch("tap.github_demo_store.GitHubDemoStore", return_value=store),
        ):
            app = AppTest.from_file(
                str(ROOT / "pages" / "4_organization_report.py"),
                default_timeout=30,
            ).run()
            app.session_state["demo_store_access_code"] = legacy_code
            app.run()

        preview_input = next(
            item for item in app.text_input if item.label == "리포트 미리보기 코드"
        )
        preview_toggle = next(
            item
            for item in app.toggle
            if item.label == "소표본 실제값을 화면에서만 미리보기"
        )
        self.assertEqual(legacy_code, preview_input.value)
        self.assertFalse(preview_toggle.disabled)

    def test_small_n_preview_lock_survives_project_switches(self) -> None:
        legacy_code = "legacy-planning-code"
        config = DemoStoreConfig(
            enabled=True,
            owner="example",
            repo="tap-demo",
            access_code=legacy_code,
        )
        project_a, submission_a = _small_n_store_snapshot()
        project_b = deepcopy(project_a)
        project_b["project_id"] = "TAP-SMALL-N-PREVIEW-B"
        project_b["project_name"] = "소표본 화면 검증 B"
        submission_b = deepcopy(submission_a)
        submission_b["project_id"] = project_b["project_id"]
        submission_b["participant_key"] = "p_" + "b" * 64
        store = MagicMock()
        store.status.return_value = {"read_enabled": True}
        store.list_projects.return_value = [project_a, project_b]
        store.list_submissions.return_value = [submission_a, submission_b]

        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        with (
            patch(
                "tap.github_demo_store.DemoStoreConfig.from_sources",
                return_value=config,
            ),
            patch("tap.github_demo_store.GitHubDemoStore", return_value=store),
        ):
            app = AppTest.from_file(
                str(ROOT / "pages" / "4_organization_report.py"),
                default_timeout=30,
            ).run()
            app.session_state["demo_store_access_code"] = legacy_code
            app.run()
            next(item for item in app.button if item.label == "미리보기 잠금").click()
            app.run()

            project_select = next(
                item for item in app.selectbox if item.label == "프로젝트 선택"
            )
            project_select.set_value(f"store:{project_b['project_id']}")
            app.run()
            self.assertEqual(
                "",
                next(
                    item
                    for item in app.text_input
                    if item.label == "리포트 미리보기 코드"
                ).value,
            )
            self.assertTrue(
                next(
                    item
                    for item in app.toggle
                    if item.label == "소표본 실제값을 화면에서만 미리보기"
                ).disabled
            )

            next(
                item for item in app.selectbox if item.label == "프로젝트 선택"
            ).set_value(f"store:{project_a['project_id']}")
            app.run()
            self.assertEqual(
                "",
                next(
                    item
                    for item in app.text_input
                    if item.label == "리포트 미리보기 코드"
                ).value,
            )
            self.assertTrue(
                next(
                    item
                    for item in app.toggle
                    if item.label == "소표본 실제값을 화면에서만 미리보기"
                ).disabled
            )

    def test_small_n_preview_rejects_non_demo_store_project(self) -> None:
        config = DemoStoreConfig(
            enabled=True,
            owner="example",
            repo="tap-demo",
            report_preview_code="report-preview-secret",
        )
        project, submission = _small_n_store_snapshot()
        project["demo_only"] = False
        store = MagicMock()
        store.status.return_value = {"read_enabled": True}
        store.list_projects.return_value = [project]
        store.list_submissions.return_value = [submission]

        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        with (
            patch(
                "tap.github_demo_store.DemoStoreConfig.from_sources",
                return_value=config,
            ),
            patch("tap.github_demo_store.GitHubDemoStore", return_value=store),
        ):
            app = AppTest.from_file(
                str(ROOT / "pages" / "4_organization_report.py"),
                default_timeout=30,
            ).run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertFalse(
            any(item.label == "리포트 미리보기 코드" for item in app.text_input)
        )
        self.assertTrue(
            any(
                item.label == "CSV 파일로 직접 비교하기 · 보조 기능"
                for item in app.expander
            )
        )

    def test_five_paired_store_participants_keep_normal_public_report(self) -> None:
        config = DemoStoreConfig(
            enabled=True,
            owner="example",
            repo="tap-demo",
            report_preview_code="report-preview-secret",
        )
        project, submission = _small_n_store_snapshot()
        submissions: list[dict[str, object]] = []
        for index in range(5):
            item = deepcopy(submission)
            item["participant_key"] = f"p_{index:064x}"
            item["updated_at"] = f"2026-10-01T12:00:0{index}Z"
            submissions.append(item)
        store = MagicMock()
        store.status.return_value = {"read_enabled": True}
        store.list_projects.return_value = [project]
        store.list_submissions.return_value = submissions

        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        with (
            patch(
                "tap.github_demo_store.DemoStoreConfig.from_sources",
                return_value=config,
            ),
            patch("tap.github_demo_store.GitHubDemoStore", return_value=store),
        ):
            app = AppTest.from_file(
                str(ROOT / "pages" / "4_organization_report.py"),
                default_timeout=30,
            ).run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertFalse(
            any(item.label == "리포트 미리보기 코드" for item in app.text_input)
        )
        self.assertIn(
            "인쇄용 리포트 HTML",
            {item.label for item in app.get("download_button")},
        )
        self.assertTrue(any(item.label == "교육 전 참여" for item in app.metric))
        frames = app.get("iframe")
        self.assertEqual(1, len(frames))
        frame = frames[0]
        self.assertEqual("iframe", frame.type)
        self.assertIn("<svg", frame.proto.srcdoc)
        self.assertIn('data-axis-count="3"', frame.proto.srcdoc)
        self.assertIn("<table", frame.proto.srcdoc)
        self.assertTrue(frame.proto.scrolling)
        self.assertTrue(frame.proto.HasField("tab_index"))
        self.assertEqual(0, frame.proto.tab_index)

    def test_organization_report_does_not_auto_show_sample(self) -> None:
        app = AppTest.from_file(str(ROOT / "pages" / "4_organization_report.py"), default_timeout=30).run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertTrue(any(item.label == "예시 리포트 보기" and not item.value for item in app.checkbox))
        self.assertTrue(
            any(
                item.label == "CSV 파일로 직접 비교하기 · 보조 기능"
                for item in app.expander
            )
        )
        self.assertTrue(any("표시할 실제 결과가 없습니다" in str(item.value) for item in app.info))
        self.assertFalse(any("예시 데이터를 표시" in str(item.value) for item in app.info))

    def test_organization_report_sample_option_renders_without_widget_errors(self) -> None:
        app = AppTest.from_file(
            str(ROOT / "pages" / "4_organization_report.py"), default_timeout=30
        ).run()
        sample_toggle = next(
            item for item in app.checkbox if item.label == "예시 리포트 보기"
        )

        sample_toggle.set_value(True)
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertTrue(
            any("모든 수치와 변화량은 합성 예시" in str(item.value) for item in app.warning)
        )
        self.assertTrue(
            any("교육 전후 비교 포인트" in str(item.value) for item in app.markdown)
        )
        self.assertEqual(
            {"교육 전 참여", "교육 후 참여", "전·후 비교 참여자", "사후 이탈률"},
            {item.label for item in app.metric},
        )
        self.assertTrue(
            any(
                item.label == "CSV 파일로 직접 비교하기 · 보조 기능"
                for item in app.expander
            )
        )

    def test_incomplete_post_does_not_render_change_report(self) -> None:
        questions = questions_for_factors(["CORE-CO"])
        pre = {str(row["question_code"]): 2 for row in questions}
        post = {str(row["question_code"]): 4 for row in questions[:3]}
        app = AppTest.from_file(str(ROOT / "pages" / "3_individual_report.py"), default_timeout=30).run()
        app.session_state["selected_factors"] = ["CORE-CO"]
        app.session_state["responses_by_phase"] = {"pre": pre, "post": post}
        app.session_state["assessment_completed_by_phase"] = {"pre": True, "post": False}
        app.run()
        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertTrue(any("모두 완료" in str(item.value) for item in app.warning))
        self.assertFalse(any("교육 전·후 비교" in str(item.value) for item in app.markdown))
        self.assertTrue(any("교육 전 완료 결과" in str(item.value) for item in app.markdown))
        saved = next(item for item in app.metric if item.label == "저장된 응답")
        self.assertEqual(f"3/{len(questions)}문항", saved.value)

    def test_transfer_factor_is_suppressed_below_minimum_n(self) -> None:
        rows = []
        for participant in ("P1", "P2", "P3", "P4", "P5"):
            rows.extend(
                [
                    {"participant_id": participant, "factor_code": "F1", "factor_name_ko": "업무 소통", "score_1_to_5": 3.0, "session_type": "pre"},
                    {"participant_id": participant, "factor_code": "F1", "factor_name_ko": "업무 소통", "score_1_to_5": 4.0, "session_type": "post", "opportunity_1_to_5": 5.0 if participant == "P1" else None},
                ]
            )
        summary = build_pre_post_group_summary(pd.DataFrame(rows), min_group_n=5)
        detail = summary["transfer_factors"]["업무 적용기회"]
        self.assertEqual(detail["n"], 1)
        self.assertIsNone(detail["mean"])

    def test_cross_factor_rows_do_not_inflate_paired_people(self) -> None:
        frame = pd.DataFrame(
            [
                {"participant_id": "P1", "factor_code": "F1", "factor_name_ko": "F1", "score_1_to_5": 3, "session_type": "pre"},
                {"participant_id": "P1", "factor_code": "F2", "factor_name_ko": "F2", "score_1_to_5": 4, "session_type": "post"},
            ]
        )
        summary = build_pre_post_group_summary(frame, min_group_n=1)
        self.assertEqual(summary["paired_participant_count"], 0)

    def test_completed_session_rows_match_personal_common_item_change(self) -> None:
        questions = questions_for_factors(["CORE-CO"])
        self.assertEqual(4, len(questions))
        codes = [str(row["question_code"]) for row in questions]
        rows = completed_session_factor_rows(
            questions,
            {
                "pre": dict(zip(codes, [1, 1, 1, 5], strict=True)),
                "post": dict(zip(codes, [5, 5, 5, 0], strict=True)),
            },
            {"pre": True, "post": True},
            participant_id="P1",
            project_id="PROJECT-1",
            assessment_version="TAP-1",
            target_level="staff",
            assessment_dates={"pre": "2026-08-01", "post": "2026-10-01"},
            post_transfer_responses={"time_process_support": 4},
        )
        by_phase = {row["session_type"]: row for row in rows}

        self.assertEqual(1.0, by_phase["pre"]["score_1_to_5"])
        self.assertEqual(5.0, by_phase["post"]["score_1_to_5"])
        self.assertEqual(4, by_phase["pre"]["valid_items"])
        self.assertEqual(3, by_phase["post"]["valid_items"])
        self.assertEqual(1, by_phase["post"]["na_items"])
        self.assertEqual(4, by_phase["post"]["time_process_support_1_to_5"])

        clean, errors, _ = prepare_group_results(
            pd.DataFrame(rows), load_competencies(), require_metadata=True
        )
        self.assertEqual([], errors)
        summary = build_pre_post_group_summary(clean, min_group_n=1)
        self.assertEqual(4.0, summary["comparison_rows"][0]["change"])


if __name__ == "__main__":
    unittest.main()
