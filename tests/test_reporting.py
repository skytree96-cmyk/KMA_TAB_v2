from __future__ import annotations

import re
import unittest
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from tap.data import questions_for_factors
from tap.reporting import (
    build_organization_report_model,
    build_pre_post_group_summary,
    organization_report_fragment,
    prepare_group_results,
    printable_organization_report_html,
)


COMPETENCIES = [
    {
        "factor_code": "F1",
        "factor_name_ko": "공식 한글명",
        "active_for_scoring": True,
    }
]
ROOT = Path(__file__).resolve().parents[1]


class ReportingTests(unittest.TestCase):
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
        self.assertIn("짝지어진 N=7", html)
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
            any("교육 전·후 짝지어진 비교" in str(item.value) for item in app.markdown)
        )
        self.assertTrue(any(item.label == "관찰 변화 평균" for item in app.metric))

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
        self.assertFalse(any("교육 전·후 짝지어진 비교" in str(item.value) for item in app.markdown))

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


if __name__ == "__main__":
    unittest.main()
