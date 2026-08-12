from __future__ import annotations

import unittest

from tap.dashboard import completion_rate, load_dashboard_demo, validate_dashboard_demo


class DashboardTests(unittest.TestCase):
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
