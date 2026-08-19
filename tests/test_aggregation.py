import unittest

from tap.aggregation import aggregate_factor_results, aggregate_paired_factor_results


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

    def test_pre_post_uses_paired_participants_only(self):
        rows = []
        for participant_id, pre, post in (
            ("P1", 2.0, 4.0),
            ("P2", 3.0, 4.0),
            ("P3", 4.0, 5.0),
            ("P4", 1.0, 2.0),
            ("P5", 5.0, 5.0),
        ):
            rows.extend(
                [
                    {
                        "participant_id": participant_id,
                        "factor_code": "F",
                        "factor_name_ko": "역량",
                        "assessment_phase": "pre",
                        "score_1_to_5": pre,
                    },
                    {
                        "participant_id": participant_id,
                        "factor_code": "F",
                        "factor_name_ko": "역량",
                        "assessment_phase": "post",
                        "score_1_to_5": post,
                    },
                ]
            )
        rows.append(
            {
                "participant_id": "POST_ONLY",
                "factor_code": "F",
                "assessment_phase": "post",
                "score_1_to_5": 1.0,
            }
        )
        result = aggregate_paired_factor_results(rows)[0]
        self.assertEqual(result["pre_n"], 5)
        self.assertEqual(result["post_n"], 6)
        self.assertEqual(result["paired_n"], 5)
        self.assertEqual(result["post_only_n"], 1)
        self.assertEqual(result["pre_mean"], 3.0)
        self.assertEqual(result["post_mean"], 4.0)
        self.assertEqual(result["observed_change"], 1.0)

    def test_pre_post_excludes_na_missing_and_nonfinite(self):
        rows = [
            {"participant_id": "P1", "factor_code": "F", "phase": "pre", "score_1_to_5": 3},
            {"participant_id": "P1", "factor_code": "F", "phase": "post", "score_1_to_5": 4},
            {"participant_id": "P2", "factor_code": "F", "phase": "pre", "score_1_to_5": 3},
            {"participant_id": "P2", "factor_code": "F", "phase": "post", "score_1_to_5": None},
            {"participant_id": "P3", "factor_code": "F", "phase": "pre", "score_1_to_5": 0},
            {"participant_id": "P3", "factor_code": "F", "phase": "post", "score_1_to_5": 4},
            {"participant_id": "P4", "factor_code": "F", "phase": "pre", "score_1_to_5": float("nan")},
        ]
        result = aggregate_paired_factor_results(rows, min_group_n=2)[0]
        self.assertEqual(result["pre_n"], 2)
        self.assertEqual(result["post_n"], 2)
        self.assertEqual(result["paired_n"], 1)
        self.assertEqual(result["attrition_n"], 1)
        self.assertIsNone(result["observed_change"])
        self.assertEqual(result["status"], "비공개(전·후 유효응답 N<2)")

    def test_paired_duplicate_rows_do_not_inflate_n(self):
        rows = [
            {"participant_id": "P1", "factor_code": "F", "pre_score": 2, "post_score": 4},
            {"participant_id": "P1", "factor_code": "F", "pre_score": 4, "post_score": 4},
            {"participant_id": "P2", "factor_code": "F", "pre_score": 3, "post_score": 5},
        ]
        result = aggregate_paired_factor_results(rows, min_group_n=2)[0]
        self.assertEqual(result["paired_n"], 2)
        self.assertEqual(result["pre_mean"], 3.0)
        self.assertEqual(result["post_mean"], 4.5)
        self.assertEqual(result["observed_change"], 1.5)


if __name__ == "__main__":
    unittest.main()
