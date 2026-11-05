from __future__ import annotations

import re
import unittest

from tap.account_ui_kit import change_level, change_scale, change_summary


class ChangeBandTests(unittest.TestCase):
    def test_web_bands_match_the_pdf(self):
        from tap.account_report_pdf import effect_level
        for change in (None, -0.5, -0.2, -0.19, 0.0, 0.19, 0.2, 0.49, 0.5, 1.2, 0.495, -0.195):
            self.assertEqual(change_level(change), effect_level(change), change)


class SummaryTileTests(unittest.TestCase):
    def test_equal_weighted_means_change_and_largest_rise(self):
        html = change_summary([("고객지향", 3.0, 3.5), ("협업", 2.0, 3.0), ("실행력", 4.0, None)])
        values = re.findall(r"<strong>(.*?)(?:<small>(.*?)</small>)?</strong>", html)
        self.assertEqual(values, [("2.50", "/ 5"), ("3.25", "/ 5"), ("+0.75", "크게 향상"), ("협업", "+1.00")])
        self.assertIn("상승 폭 1위", html)

    def test_no_rise_names_the_largest_change_instead_and_flags_a_drop(self):
        html = change_summary([("고객지향", 3.5, 3.0), ("협업", 3.0, 2.9)])
        self.assertNotIn("상승 폭 1위", html)
        self.assertIn("변화가 가장 큰 역량", html)
        self.assertEqual(html.count("tap-stat is-low"), 1)  # the mean change, -0.30
        self.assertEqual(change_summary([("고객지향", None, 3.0)]), "")


class ChangeScaleTests(unittest.TestCase):
    def test_rings_dots_and_bands_on_one_scale(self):
        html = change_scale([("고객지향", "교육 전후 6명", 3.0, 4.0, 1.0, ""),
                             ("협업", "교육 전후 6명", 4.0, 3.5, -0.5, "")])
        self.assertIn('class="tap-srow__pre" style="left:50.0%"', html)
        self.assertIn('class="tap-srow__post" style="left:75.0%"', html)
        self.assertIn('class="tap-lv is-big">크게 향상', html)
        self.assertIn('class="tap-lv is-down">하락', html)
        self.assertIn("tap-srow__fill is-down", html)
        self.assertIn('style="left:62.5%;width:12.5%"', html)  # the stretch runs from post to pre on a drop

    def test_hidden_rows_say_why_and_escape_text(self):
        from tap.account_reports import summary_scale_rows
        rows = summary_scale_rows([
            {"factor_name_ko": "<협업>", "paired_n": 3, "pre_mean": None, "post_mean": None, "observed_change": None},
            {"factor_name_ko": "실행력", "paired_n": 6, "pre_mean": None, "post_mean": None, "observed_change": None},
        ])
        html = change_scale(rows)
        self.assertIn("&lt;협업&gt;", html)
        self.assertIn("비공개 · 5명 미만", html)
        self.assertIn(">미산출<", html)
        self.assertNotIn("tap-srow__post", html)


if __name__ == "__main__":
    unittest.main()
