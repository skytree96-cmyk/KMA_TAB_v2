import unittest

from tap.data import (
    integrity_report,
    load_competencies,
    load_course_map,
    load_pilot_item_candidates,
    load_questions,
)


class DataIntegrityTests(unittest.TestCase):
    def test_full_original_inventory_and_operational_bank(self):
        questions = load_questions()
        self.assertEqual(len(questions), 144)
        self.assertEqual(sum(q["active"] for q in questions), 124)
        self.assertEqual(len({q["question_code"] for q in questions}), 144)

    def test_retired_grade_factors(self):
        competencies = load_competencies()
        retired = {c["factor_code"] for c in competencies if not c["active_for_scoring"]}
        self.assertEqual(retired, {"GRD1_COMP", "GRD2_COMP", "GRD3_COMP", "GRD4_COMP", "GRD5_COMP"})

    def test_integrity_report(self):
        report = integrity_report()
        self.assertTrue(report["unique_question_codes"])
        self.assertEqual(report["unmapped_question_factors"], [])
        self.assertEqual(report["unexpected_empty_competencies"], [])
        self.assertEqual(report["factors_not_four_items"], {})

    def test_every_active_factor_has_course_mapping(self):
        competencies = load_competencies()
        active = {c["factor_code"] for c in competencies if c["active_for_scoring"]}
        mapped = {m["factor_code"] for m in load_course_map()}
        self.assertEqual(active - mapped, set())

    def test_pilot_candidates_are_separate_and_inactive(self):
        rows = load_pilot_item_candidates()
        self.assertEqual(len(rows), 16)
        self.assertEqual(len({row["question_code"] for row in rows}), 16)
        self.assertTrue(all(not row["active_for_scoring"] for row in rows))


if __name__ == "__main__":
    unittest.main()
