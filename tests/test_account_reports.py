import unittest
from tap.account_reports import UNASSIGNED_TEAM, summarize_by_team, summarize_project
from tap.data import questions_for_factors


class AccountReportTests(unittest.TestCase):
    def records(self,count):
        questions=questions_for_factors(["CORE-CO"])
        project={"config":{"selected_factors":["CORE-CO"],"question_snapshot":questions}}
        rows=[{"user_id":str(i),"pre_completed":True,"post_completed":True,"pre_payload":{"responses":{q["question_code"]:3 for q in questions}},"post_payload":{"responses":{q["question_code"]:4 for q in questions}}} for i in range(count)]
        return project,rows

    def test_small_group_cannot_disclose_mean(self):
        project,rows=self.records(4)
        result=summarize_project(project,rows)
        self.assertEqual(result[0]["paired_n"],4)
        for key in ["pre_mean","post_mean","observed_change"]:
            self.assertIsNone(result[0][key])

    def test_five_valid_pairs_disclose_and_na_does_not_inflate_count(self):
        project,rows=self.records(5)
        result=summarize_project(project,rows)
        self.assertEqual(result[0]["pre_mean"],3)
        self.assertEqual(result[0]["post_mean"],4)
        self.assertEqual(result[0]["observed_change"],1)
        rows[0]["post_payload"]["responses"]={code:0 for code in rows[0]["post_payload"]["responses"]}
        result=summarize_project(project,rows)
        self.assertEqual(result[0]["paired_n"],4)
        self.assertIsNone(result[0]["observed_change"])

    def test_team_summaries_group_by_department_with_unassigned_last(self):
        project, rows = self.records(12)
        for index, row in enumerate(rows):
            row["department"] = ("영업팀", "개발팀", "")[index % 3] if index < 11 else None
        teams = summarize_by_team(project, rows)
        self.assertEqual([team["team"] for team in teams], ["개발팀", "영업팀", UNASSIGNED_TEAM])
        self.assertEqual([team["paired_n"] for team in teams], [4, 4, 4])
        self.assertTrue(all(team["summaries"][0]["post_mean"] is None for team in teams))

class IndividualAccountReportTests(unittest.TestCase):
    records = AccountReportTests.records

    def test_individual_report_is_explicit_scoped_and_not_suppressed_by_group_size(self):
        from streamlit.testing.v1 import AppTest
        from types import SimpleNamespace
        from unittest.mock import Mock
        project, rows = self.records(1)
        project["id"] = "project-a"
        rows[0].update(id="assignment-a", user_name="홍길동", login_id="UserA")
        rows.append({"id": "incomplete", "user_id": "2", "user_name": "미완료", "login_id": "UserB", "pre_completed": True, "post_completed": False})
        read = Mock(return_value=rows)
        app = AppTest.from_string("import streamlit as st\nfrom tap.account_reports import render_project_report\nrender_project_report(st.session_state['store'], 'token', st.session_state['project'])", default_timeout=30)
        access = Mock()
        app.session_state["store"] = SimpleNamespace(project_results=read, record_report_access=access)
        app.session_state["project"] = project
        app.run()
        self.assertFalse(app.exception)
        read.assert_called_once_with("token", "project-a")
        self.assertFalse(app.dataframe)
        self.assertEqual(app.selectbox[0].options, ["홍길동 · UserA"])
        self.assertIsNone(app.selectbox[0].value)
        access.assert_not_called()
        app.selectbox[0].set_value("assignment-a").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe), 1)
        # Opening a person's report leaves one access record per session, not one per rerun.
        access.assert_called_once()
        self.assertEqual(access.call_args.args[1:4], ("project-a", "view_individual_report", "assignment-a"))
        self.assertEqual(float(app.dataframe[0].value.iloc[0]["변화"]), 1.0)
        self.assertTrue(any("5명 이상" in item.value for item in app.info))
        app.text_input[0].set_value("USERA").run()
        self.assertEqual(len(app.dataframe), 1)
        app.text_input[0].set_value("다른 회사").run()
        self.assertFalse(app.dataframe)
        self.assertFalse(app.selectbox)
        app.text_input[0].set_value("").run()
        self.assertIsNone(app.selectbox[0].value)
        self.assertFalse(app.dataframe)


class IndividualReportCourseTests(unittest.TestCase):
    def test_individual_pdf_lists_two_courses_for_each_of_three_competencies(self):
        from unittest.mock import patch
        from tap.account_reports import individual_report_pdf
        factors = ["CORE-CL", "JOB-PS", "LEAD-PD", "CORE-CO"]
        questions = questions_for_factors(factors)
        config = {"selected_factors": factors, "target_means": {code: 3.5 for code in factors}, "target_level": "manager",
                  "delivery_preference": "all", "question_snapshot": questions}
        pre = {q["question_code"]: 2 for q in questions}
        post = {q["question_code"]: 4 if q["factor_code"] == "CORE-CO" else 2 for q in questions}
        with patch("tap.account_report_pdf.build_report_pdf", return_value=b"%PDF") as build:
            individual_report_pdf({"name": "리더십", "config": config}, questions, pre, post, "참여자")
        courses = build.call_args.kwargs["courses"]
        # Same picks as the participant screen: three weak competencies, a public course and an e-learning course each.
        self.assertEqual(len(courses), 6)
        self.assertEqual({row["factor_code"] for row in courses}, {"CORE-CL", "JOB-PS", "LEAD-PD"})
        self.assertEqual([row["source"] for row in courses].count("studio_elearning"), 3)


class ReportDownloadTests(unittest.TestCase):
    records = AccountReportTests.records

    def test_organization_pdf_prints_the_department_page_only_with_two_shown_departments(self):
        try:
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("pypdf is not installed")
        from io import BytesIO
        from types import SimpleNamespace
        from tap.account_reports import export_report_pdf
        project, results = self.records(10)
        project.update(id="project-a", name="교육 A")
        for i, row in enumerate(results):
            row.update(id=f"assignment-{i}", user_name=f"참여자{i}", login_id=f"user{i}", department="영업팀" if i < 5 else "기획팀")

        def text(rows):
            pdf = export_report_pdf(SimpleNamespace(project_results=lambda token, project_id: rows,
                                                    record_report_access=lambda *args, **kwargs: None), "token", project)
            return "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)

        both = text(results)
        self.assertIn("팀(부서)별 교육 후 평균", both)
        self.assertIn("영업팀", both)
        self.assertIn("기획팀", both)
        for row in results[5:]:
            row["department"] = "영업팀"
        self.assertNotIn("팀(부서)별 교육 후 평균", text(results))

    def test_exports_recheck_authorization_and_match_the_selected_person_project(self):
        from tap.account_reports import export_report_pdf
        from tap.account_store import AuthorizationError, ValidationError
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        project, results = self.records(5)
        project.update(id="project-a",name="교육 A")
        for i,row in enumerate(results):
            row.update(id=f"assignment-{i}",user_name=f"참여자{i}",login_id=f"user{i}")
        store = SimpleNamespace(project_results=Mock(return_value=results), record_report_access=Mock())
        with patch("tap.account_report_pdf.build_report_pdf", return_value=b"%PDF-test") as build:
            self.assertEqual(export_report_pdf(store, "token", project, "assignment-2"), b"%PDF-test")
            self.assertEqual(build.call_args.kwargs["subject"], "참여자2 · user2")
            self.assertEqual(build.call_args.kwargs["kind"], "individual")
            self.assertNotIn("heatmap", build.call_args.kwargs)
            self.assertEqual(store.record_report_access.call_args.args[1:4], ("project-a", "download_individual_pdf", "assignment-2"))
            store.project_results.assert_called_with("token", "project-a")
            export_report_pdf(store, "token", project)
            self.assertEqual(store.record_report_access.call_args.args[1:3], ("project-a", "download_organization_pdf"))
            self.assertEqual(build.call_args.kwargs["kind"], "organization")
            self.assertEqual(build.call_args.args[1][0]["valid_n"], 5)
            # No department entered: one "부서 미지정" row, which the PDF leaves out (fewer than two departments).
            grid = build.call_args.kwargs["heatmap"]
            self.assertEqual([row["team"] for row in grid["rows"]], ["부서 미지정"])
            self.assertEqual(grid["rows"][0]["paired_n"], 5)
            with self.assertRaises(ValidationError): export_report_pdf(store, "token", project, "foreign-id")
            store.project_results.return_value = results[:4]
            with self.assertRaises(ValidationError): export_report_pdf(store, "token", project)
            store.project_results.side_effect = AuthorizationError("denied")
            with self.assertRaises(AuthorizationError): export_report_pdf(store, "revoked", project, "assignment-2")
