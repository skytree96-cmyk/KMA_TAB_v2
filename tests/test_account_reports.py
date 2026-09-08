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