from __future__ import annotations

import unittest

import pandas as pd

from tap.reporting import (
    build_organization_report_model,
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


if __name__ == "__main__":
    unittest.main()
