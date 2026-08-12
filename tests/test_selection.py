from __future__ import annotations

import unittest

from tap.data import load_competencies
from tap.selection import applicable_to_level, sanitize_selection, selection_errors


class SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = load_competencies()

    def test_valid_three_specialty_and_one_job(self) -> None:
        selected = ["AI_USE", "PLAN_STR", "DATA_ANA", "SALES_CORE"]
        self.assertEqual(selection_errors(selected, self.rows), [])

    def test_fourth_specialty_is_rejected(self) -> None:
        selected = ["AI_USE", "PLAN_STR", "DATA_ANA", "DX_APPLY"]
        errors = selection_errors(selected, self.rows)
        self.assertTrue(any("전문·미래역량" in error for error in errors))

    def test_second_job_function_is_rejected(self) -> None:
        errors = selection_errors(["SALES_CORE", "MKT_CORE"], self.rows)
        self.assertTrue(any("직무역량" in error for error in errors))

    def test_sanitize_removes_inapplicable_and_over_limit(self) -> None:
        selected = ["AI_USE", "PLAN_STR", "DATA_ANA", "DX_APPLY", "STRAT_CORE"]
        sanitized = sanitize_selection(selected, self.rows, "staff")
        self.assertEqual(sanitized, ["AI_USE", "PLAN_STR", "DATA_ANA"])

    def test_executive_job_module_applicability(self) -> None:
        strategy = next(row for row in self.rows if row["factor_code"] == "STRAT_CORE")
        sales = next(row for row in self.rows if row["factor_code"] == "SALES_CORE")
        self.assertTrue(applicable_to_level(strategy, "executive"))
        self.assertFalse(applicable_to_level(sales, "executive"))


if __name__ == "__main__":
    unittest.main()
