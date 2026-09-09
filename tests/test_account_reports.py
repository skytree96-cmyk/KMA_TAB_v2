import unittest
from tap.account_reports import summarize_project
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
        app.session_state["store"] = SimpleNamespace(project_results=read)
        app.session_state["project"] = project
        app.run()
        self.assertFalse(app.exception)
        read.assert_called_once_with("token", "project-a")
        self.assertFalse(app.dataframe)
        self.assertEqual(app.selectbox[0].options, ["홍길동 · UserA"])
        self.assertIsNone(app.selectbox[0].value)
        app.selectbox[0].set_value("assignment-a").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe), 1)
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


class ReportDownloadTests(unittest.TestCase):
    records = AccountReportTests.records

    def test_exports_recheck_authorization_and_match_the_selected_person_project(self):
        from tap.account_reports import export_report_pdf
        from tap.account_store import AuthorizationError, ValidationError
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        project, results = self.records(5)
        project.update(id="project-a",name="교육 A")
        for i,row in enumerate(results):
            row.update(id=f"assignment-{i}",user_name=f"참여자{i}",login_id=f"user{i}")
        store = SimpleNamespace(project_results=Mock(return_value=results))
        with patch("tap.account_report_pdf.build_report_pdf", return_value=b"%PDF-test") as build:
            self.assertEqual(export_report_pdf(store, "token", project, "assignment-2"), b"%PDF-test")
            self.assertEqual(build.call_args.kwargs["subject"], "참여자2 · user2")
            self.assertEqual(build.call_args.kwargs["kind"], "individual")
            store.project_results.assert_called_with("token", "project-a")
            export_report_pdf(store, "token", project)
            self.assertEqual(build.call_args.kwargs["kind"], "organization")
            self.assertEqual(build.call_args.args[1][0]["valid_n"], 5)
            with self.assertRaises(ValidationError): export_report_pdf(store, "token", project, "foreign-id")
            store.project_results.return_value = results[:4]
            with self.assertRaises(ValidationError): export_report_pdf(store, "token", project)
            store.project_results.side_effect = AuthorizationError("denied")
            with self.assertRaises(AuthorizationError): export_report_pdf(store, "revoked", project, "assignment-2")
