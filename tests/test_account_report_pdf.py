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
                                (.5,"크게 향상"), (.4999,"향상"), (.2,"향상"),
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
        self.assertTrue(all(len(g) <= 12 for g in groups))
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

    def test_long_course_list_continues_across_pages(self):
        url = "https://www.kma.or.kr/usrs/eduRegMgnt/eduRegInfoDetailForm.do?" + "p_crscd=110083&CRSSEQ_ID=&" * 6
        courses = [{"title": f"리더십 과정 {i} " * 4, "delivery_label": "집합", "factor_name_ko": "문제해결력",
                    "reason": "교육 후 3.00점, 목표 3.50점보다 0.50점 낮음 · 교육 전보다 0.10점 높음",
                    "schedule": "다음 개강 2026-12-01 · 여의도 · 2일 · 14시간", "url": url,
                    "advice": "교육 전과 큰 차이가 없습니다. 지난 교육 내용이 업무에 맞았는지 함께 점검하세요." if i == 1 else ""}
                   for i in range(1, 10)]
        transfer = {"n": 3, "disclosed": False, "factors": [], "barriers": []}
        pdf = build_report_pdf(PROJECT, [row()], kind="organization", subject="조직 전체", participant_count=5,
                               transfer=transfer, courses=courses)
        self.assertTrue(pdf.startswith(b"%PDF-"))

    def test_courses_are_grouped_under_their_competency_in_one_box(self):
        try:
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("pypdf is not installed")
        # recommend_courses fills source by source, so a competency's second course arrives after other competencies.
        def course(title, competency):
            return {"title": title, "source": "public_edu_center", "factor_name_ko": competency, "advice": "",
                    "reason": "교육 후 3.00점, 목표 3.50점보다 0.50점 낮음", "score": 3.0, "target": 3.5, "change": 0.0}
        courses = [course("문제해결 공개과정", "문제해결력"), course("실행력 공개과정", "실행력"), course("문제해결 이러닝", "문제해결력")]
        pdf = build_report_pdf(PROJECT, [row()], kind="individual", subject="참여자", courses=courses)
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
        self.assertLess(text.index("문제해결 이러닝"), text.index("실행력 공개과정"))
        self.assertEqual(text.count("응답 결과"), 2)
        self.assertEqual(text.count("추천 과정"), 2)

    def test_details_show_scores_for_missing_and_hidden_rows_without_inventing_them(self):
        try:
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("pypdf is not installed")
        pdf = build_report_pdf(PROJECT, [row("F1", pre=None, post=3.0), row("F2", pre=2.0, post=4.0, n=4, name="실행력")],
                               kind="organization", subject="조직 전체", participant_count=5)
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
        self.assertIn("3.00", text)   # the one score that exists is shown
        self.assertNotIn("2.00", text)  # the small group's scores are not
        self.assertNotIn("4.00", text)
        self.assertIn("비공개", text)

    def test_summary_tiles_count_comparable_competencies_and_name_ties(self):
        try:
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("pypdf is not installed")
        project = {**PROJECT, "config": {**PROJECT["config"], "target_means": {"F1": 3.5, "F2": 3.5, "F3": 3.5}}}
        rows = [row("F1", pre=2.0, post=3.0, name="고객지향"), row("F2", pre=3.0, post=4.0, name="실행력"),
                row("F3", pre=4.0, post=3.0, name="문제해결력"), row("F4", pre=None, post=4.5, name="전략적 사고")]
        first = PdfReader(BytesIO(build_report_pdf(project, rows, kind="individual", subject="참여자"))).pages[0].extract_text()
        # F4 has no pre score, so it is outside the counts; without its target the "reached" tile would still show.
        for label in ("목표에 도달한 역량", "향상한 역량", "하락한 역량", "가장 많이 오른 역량"):
            self.assertIn(label, first)
        self.assertEqual(first.count("/ 3개"), 3)
        self.assertIn("고객지향 외 1개", first)
        # One comparable competency: the headline already says it all.
        single = PdfReader(BytesIO(build_report_pdf(project, rows[:1], kind="individual", subject="참여자"))).pages[0].extract_text()
        self.assertNotIn("향상한 역량", single)

    def test_zero_change_and_single_competency_read_as_sentences(self):
        try:
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("pypdf is not installed")
        pdf = build_report_pdf(PROJECT, [row(pre=3.0, post=3.0)], kind="individual", subject="참여자")
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
        self.assertIn("교육 전후 모두 3.00점입니다", text)
        self.assertNotIn("+0.00", text)
        # One comparable competency is not shown as both the one to spread and the one to check first.
        self.assertNotIn("우선 점검할 역량", text)

    def test_invalid_kind_rejected(self):
        with self.assertRaises(ValueError):
            build_report_pdf(PROJECT, [], kind="other", subject="test")
