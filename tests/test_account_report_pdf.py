from __future__ import annotations

from io import BytesIO
import unittest

from tap.account_insights import COURSE_INQUIRY_URL
from tap.account_report_pdf import build_report_pdf, effect_level, prepare_rows, report_summary, _chart_groups

PROJECT = {"company_name": "테스트 회원사", "name": "리더십 적용 프로젝트", "config": {
    "course_name": "리더십 역량 워크숍", "training_date": "2026-09-09"}}


def row(code="F1", pre=2.8, post=3.5, n=5, name="성장 마인드셋"):
    return {"factor_code":code, "factor_name_ko":name, "module_group":"리더십", "pre_score":pre, "post_score":post, "valid_n":n}


class AccountReportPDFTests(unittest.TestCase):
    def test_effect_thresholds_and_missing(self):
        for value, expected in [(None,"미산출"), (float("nan"),"미산출"),
                                (.5,"큰 향상"), (.4999,"향상"), (.2,"향상"),
                                (.1999,"유지"), (-.1999,"유지"), (-.2,"하락"), (-4,"하락")]:
            with self.subTest(value=value):
                self.assertEqual(effect_level(value), expected)

    def test_organization_small_groups_mask_scores_and_injected_change(self):
        rows = prepare_rows([{**row(n=4), "change":99}, row("F2",n=5)], "organization")
        self.assertIsNone(rows[0]["pre_score"])
        self.assertIsNone(rows[0]["post_score"])
        self.assertIsNone(rows[0]["change"])
        self.assertEqual(rows[1]["change"], .7)
        self.assertEqual(report_summary(rows)["valid_count"], 1)
        self.assertEqual(report_summary(rows)["selected_count"], 2)

    def test_individual_missing_and_invalid_scores_never_become_zero(self):
        rows = prepare_rows([row(pre=None), row("F2", pre=0), row("F3", pre=float("inf")),
                             row("F4", pre=True), row("F5", post=5.1), row("F6", n=1)], "individual")
        for item in rows[:5]:
            self.assertIsNone(item["change"])
        self.assertIsNone(rows[0]["pre_score"])
        self.assertEqual(rows[0]["post_score"], 3.5)
        self.assertEqual(report_summary(rows)["valid_count"], 1)
        self.assertEqual(report_summary(rows)["change"], .7)

    def test_average_uses_common_valid_competencies_with_equal_weight(self):
        prepared = prepare_rows([row(pre=1,post=2,n=10), row("F2",pre=3,post=3.2,n=50),
                                 row("F3",pre=None,post=5)], "organization")
        result = report_summary(prepared)
        self.assertEqual(result["pre"], 2)
        self.assertEqual(result["post"], 2.6)
        self.assertEqual(result["change"], .6)
        self.assertEqual(result["valid_count"], 2)

    def test_many_axes_are_partitioned_without_loss(self):
        rows = [row(str(i)) for i in range(23)]
        groups = _chart_groups(rows)
        self.assertTrue(all(len(g) <= 8 for g in groups))
        self.assertEqual([r["factor_code"] for g in groups for r in g], [str(i) for i in range(23)])

    def test_pdf_builds_for_sparse_and_many_axes_and_long_escaped_text(self):
        for count in [0, 1, 2, 3, 9, 23]:
            with self.subTest(count=count):
                rows = [row(str(i), pre=None if i % 4 == 0 else 2.8,
                            name=("복합 문제 해결 & 실행 <역량> " * 7 if i == 1 else f"성장 역량 {i}")) for i in range(count)]
                pdf = build_report_pdf(PROJECT, rows, kind="individual", subject="김테스트 <참여자>")
                self.assertTrue(pdf.startswith(b"%PDF-"))
                self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))
                self.assertGreater(len(pdf), 5000)
                try:
                    from pypdf import PdfReader
                except ImportError:
                    continue
                text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
                self.assertIn("교육효과", text)
                self.assertIn("TAP-CHANGE-1.0", text)
                if count > 1:
                    self.assertIn("복합 문제 해결", text)
                if count > 2:
                    self.assertIn(f"성장 역량 {count - 1}", text)

    def test_followup_continues_on_the_details_page_when_it_fits(self):
        try:
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("pypdf is not installed")
        courses = [{"title": "논리적 문제해결과 의사결정", "delivery_label": "집합", "factor_name_ko": "문제해결력",
                    "reason": "교육 후 3.00점, 목표 3.50점보다 0.50점 낮음", "advice": ""}]
        pdf = build_report_pdf(PROJECT, [row()], kind="individual", subject="참여자", courses=courses)
        last = PdfReader(BytesIO(pdf)).pages[-1].extract_text()
        self.assertIn("역량별 결과와 보완 가이드", last)
        self.assertIn("보완 학습 제안", last)
        self.assertNotIn("맞춤형 교육 문의", last)

    def test_organization_followup_links_to_custom_training_inquiry(self):
        try:
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("pypdf is not installed")
        transfer = {"n": 3, "disclosed": False, "factors": [], "barriers": []}
        pdf = build_report_pdf(PROJECT, [row()], kind="organization", subject="조직 전체", participant_count=5,
                               transfer=transfer, courses=[])
        uris = [annot.get_object()["/A"]["/URI"] for page in PdfReader(BytesIO(pdf)).pages for annot in page.get("/Annots", [])]
        self.assertEqual(uris, [COURSE_INQUIRY_URL])

    def test_invalid_kind_rejected(self):
        with self.assertRaises(ValueError):
            build_report_pdf(PROJECT, [], kind="other", subject="test")
