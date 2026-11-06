from __future__ import annotations

import unittest

from tap.account_store import AuthorizationError, ValidationError, hash_password
# Import the module, not the class: a TestCase name here would run the whole store suite again.
from tests import test_account_store as store_tests

INITIAL = store_tests.INITIAL


class LearningInterestStoreTests(unittest.TestCase):
    setUp = store_tests.AccountStoreTests.setUp
    user = store_tests.AccountStoreTests.user
    project = store_tests.AccountStoreTests.project
    assignment = store_tests.AccountStoreTests.assignment
    payload = store_tests.AccountStoreTests.payload

    @classmethod
    def setUpClass(cls):
        cls.seed_hash = hash_password(INITIAL)

    def test_pre_test_keeps_up_to_three_of_its_own_competencies(self):
        _, token, project, assignment = self.assignment()
        bad = [["NOT-A-CODE"], ["CORE-CO", "CORE-CO"], ["CORE-CO", "a", "b", "c"], "CORE-CO"]
        for interests in bad:
            with self.subTest(interests=interests), self.assertRaises(ValidationError):
                self.store.save_assessment(token, assignment["id"], "pre", {**self.payload(project), "learning_interests": interests}, True)
        saved = self.store.save_assessment(token, assignment["id"], "pre", {**self.payload(project), "learning_interests": ["CORE-CO"]}, True)
        self.assertEqual(saved["payload"]["learning_interests"], ["CORE-CO"])
        results = self.store.company_results(self.admin, project["company_id"])
        self.assertEqual(results[0]["pre_payload"]["learning_interests"], ["CORE-CO"])
        self.assertIsNotNone(results[0]["pre_completed_at"])

    def test_company_results_stay_inside_the_company(self):
        _, _, project, assignment = self.assignment()
        _, manager_a = self.user("company", suffix="manager-a")
        _, manager_b = self.user("company", company=self.b, suffix="manager-b")
        self.assertEqual([row["id"] for row in self.store.company_results(manager_a)], [assignment["id"]])
        # A manager always gets their own company, whatever id they pass.
        self.assertEqual(self.store.company_results(manager_b, self.a["id"]), [])
        with self.assertRaises(ValidationError):
            self.store.company_results(self.admin)
        _, participant = self.user(suffix="002")
        with self.assertRaises(AuthorizationError):
            self.store.company_results(participant)


if __name__ == "__main__":
    unittest.main()
