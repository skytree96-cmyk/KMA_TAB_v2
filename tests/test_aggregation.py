import unittest

from tap.aggregation import aggregate_factor_results


class AggregationTests(unittest.TestCase):
    def test_small_n_is_suppressed(self):
        rows = [
            {"participant_id": f"P{i}", "factor_code": "F", "factor_name_ko": "역량", "score_1_to_5": 3.0}
            for i in range(4)
        ]
        result = aggregate_factor_results(rows)[0]
        self.assertIsNone(result["group_mean"])
        self.assertEqual(result["status"], "비공개(N<5)")

    def test_n_five_is_shown(self):
        rows = [
            {"participant_id": f"P{i}", "factor_code": "F", "factor_name_ko": "역량", "score_1_to_5": 3.0}
            for i in range(5)
        ]
        result = aggregate_factor_results(rows)[0]
        self.assertEqual(result["group_mean"], 3.0)

    def test_duplicate_rows_do_not_inflate_participant_n(self):
        rows = [
            {"participant_id": "P1", "factor_code": "F", "factor_name_ko": "역량", "score_1_to_5": 3.0},
            {"participant_id": "P1", "factor_code": "F", "factor_name_ko": "역량", "score_1_to_5": 5.0},
            {"participant_id": "P2", "factor_code": "F", "factor_name_ko": "역량", "score_1_to_5": 3.0},
            {"participant_id": "P3", "factor_code": "F", "factor_name_ko": "역량", "score_1_to_5": 3.0},
            {"participant_id": "P4", "factor_code": "F", "factor_name_ko": "역량", "score_1_to_5": 3.0},
        ]
        result = aggregate_factor_results(rows)[0]
        self.assertEqual(result["n"], 4)
        self.assertIsNone(result["group_mean"])


if __name__ == "__main__":
    unittest.main()
